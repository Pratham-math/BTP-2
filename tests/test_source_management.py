"""Source removal and YouTube plumbing; provider responses here are fixtures."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from server.database import Curriculum, Job, Source, SourceVersion
from server.ingestion.readers import youtube_id
from server.ingestion.vision import extract_vision
from server.platform_settings import PlatformSettings
from server.providers.base import GenerationError
from server.worker.queue import JobContext, claim
from server.worker.tasks import prepare_source
from tests.test_platform import headers, platform, seed_lesson  # noqa: F401


def notes(client):
    return client.post('/api/sources', headers=headers('alice'), json={
        'kind': 'text', 'title': 'Removal fixture', 'text': 'Source content for removal checks.'}).json()


def test_remove_source_is_private_and_clears_versions(platform):
    client, factory, _ = platform
    source = notes(client)
    assert client.delete(f"/api/sources/{source['id']}", headers=headers('bob')).status_code == 404
    assert client.delete(f"/api/sources/{source['id']}", headers=headers('alice')).status_code == 200
    assert client.get('/api/sources', headers=headers('alice')).json() == []
    assert client.get(f"/api/sources/{source['id']}", headers=headers('alice')).status_code == 404
    with factory() as db:
        version = db.scalar(select(SourceVersion).where(SourceVersion.source_id == source['id']))
        assert version.evidence == []
        assert db.get(Source, source['id']).metadata_json == {}


def test_removal_deletes_original_and_previews(platform):
    client, factory, _ = platform
    source = notes(client)
    deleted = []
    client.app.state.objects.delete = deleted.append
    with factory.begin() as db:
        row = db.get(Source, source['id'])
        row.object_key = 'fixture/original.pdf'
        row.metadata_json = {'preview_keys': ['fixture/preview.png', 'fixture/original.pdf']}
    assert client.delete(f"/api/sources/{source['id']}", headers=headers('alice')).status_code == 200
    assert deleted == ['fixture/original.pdf', 'fixture/preview.png']


def test_source_rename_is_private_and_does_not_change_evidence(platform):
    client, factory, _ = platform
    source = notes(client)
    path = f"/api/sources/{source['id']}"
    assert client.patch(path, headers=headers('bob'), json={'title': 'Unauthorized rename'}).status_code == 404
    assert client.patch(path, headers=headers('alice'), json={'title': 'x'}).status_code == 422
    response = client.patch(path, headers=headers('alice'), json={'title': 'Renamed course notes'})
    assert response.status_code == 200
    renamed = response.json()
    assert renamed['title'] == 'Renamed course notes'
    assert renamed['evidence'] == source['evidence'] and renamed['version'] == source['version']
    with factory() as db:
        assert len(db.scalars(select(SourceVersion).where(SourceVersion.source_id == source['id'])).all()) == 1


def test_source_summary_includes_review_and_failed_extraction_state(platform):
    client, factory, ids = platform
    source = notes(client)
    with factory.begin() as db:
        version = db.scalar(select(SourceVersion).where(SourceVersion.source_id == source['id']))
        version.evidence = [{**version.evidence[0], 'uncertainty': ['ocr_required']}]
        job = Job(owner_id=ids['alice'], kind='source', dedup_key='summary-failed-job', state='failed', payload={'source_id': source['id']})
        db.add(job)
        db.flush()
        db.get(Source, source['id']).metadata_json = {'job_id': job.id}
    summary = client.get('/api/sources', headers=headers('alice')).json()[0]
    assert summary['block_count'] == summary['unresolved_blocks'] == summary['version'] == 1
    assert summary['job_state'] == 'failed' and summary['created_at'] > 0
    assert 'evidence' not in summary and 'input' not in summary
    assert client.get('/api/sources', headers=headers('bob')).json() == []


def test_removal_preserves_sources_in_pending_and_existing_lessons(platform):
    client, factory, ids = platform
    source = notes(client)
    with factory.begin() as db:
        version = db.scalar(select(SourceVersion).where(SourceVersion.source_id == source['id']))
        job = Job(owner_id=ids['alice'], kind='curriculum', dedup_key='removal-fixture',
                  payload={'source_version_ids': [version.id]}, state='queued')
        db.add(job)
        db.flush()
        job_id, version_id = job.id, version.id
    assert client.delete(f"/api/sources/{source['id']}", headers=headers('alice')).status_code == 409
    _, curriculum_id = seed_lesson(factory, ids, owner='teacher')
    with factory.begin() as db:
        db.get(Job, job_id).state = 'cancelled'
        curriculum = db.get(Curriculum, curriculum_id)
        blueprint = curriculum.blueprint
        blueprint['objectives'][0]['evidence'] = [{'source_version_id': version_id, 'block_id': 'text-1'}]
        curriculum.blueprint = dict(blueprint)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(curriculum, 'blueprint')
    assert client.delete(f"/api/sources/{source['id']}", headers=headers('alice')).status_code == 409


@pytest.mark.parametrize('url', ['https://m.youtube.com/watch?v=abcdefghijk',
    'https://www.youtube.com/shorts/abcdefghijk', 'https://youtube.com/live/abcdefghijk?feature=share',
    'https://youtube.com/embed/abcdefghijk', ' https://youtu.be/abcdefghijk?t=30 '])
def test_youtube_link_formats(url):
    assert youtube_id(url) == 'abcdefghijk'


@pytest.mark.parametrize('url', ['https://youtube.com:invalid/watch?v=abcdefghijk',
    'https://[invalid/watch?v=abcdefghijk', 'https://youtube.com/shorts/abcdefghijk/extra'])
def test_malformed_youtube_links_are_actionable(url):
    with pytest.raises(GenerationError):
        youtube_id(url)


def test_local_youtube_readiness_respects_provider_selection(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-not-a-real-key')
    monkeypatch.setenv('PLATFORM_TEXT_PROVIDER', 'gemini')
    settings = PlatformSettings(profile='local', text_model='fixture-gemini')
    assert settings.source_features()['youtube']
    monkeypatch.setenv('PLATFORM_TEXT_PROVIDER', 'ollama')
    assert not settings.source_features()['youtube']
    settings.vision_model = 'fixture-vision'
    assert settings.source_features()['youtube']
    monkeypatch.delenv('GEMINI_API_KEY')
    assert not settings.source_features()['youtube']


def test_youtube_extraction_worker_requires_confirmation(platform, monkeypatch, tmp_path):
    client, factory, _ = platform
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-not-a-real-key')
    settings = client.app.state.settings
    settings.youtube_sources, settings.vision_model = True, 'fixture-vision'
    response = client.post('/api/sources', headers=headers('alice'), json={
        'kind': 'youtube', 'title': 'Video fixture', 'text': 'https://youtu.be/abcdefghijk?t=90'})
    assert response.status_code == 201, response.text
    source = response.json()
    assert source['original_url'] == 'https://www.youtube.com/watch?v=abcdefghijk'
    evidence = [{'id': 'video-1', 'text': 'Fixture video-derived explanation.', 'location': '00:00–00:10',
                 'method': 'gemini-derived-notes', 'uncertainty': ['author_confirmation_required'], 'image_key': None}]
    response_body = {'accessible': True, 'duration_seconds': 10, 'evidence': evidence, 'warnings': []}
    provider = MagicMock()
    provider.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(text=json.dumps(response_body))
    monkeypatch.setattr('server.providers.gemini_text.create_client', lambda key: provider)
    monkeypatch.setattr('server.worker.tasks.StructuredAuthor.quota', lambda self: None)
    data = claim(factory, queue='generation')
    context = JobContext(factory, data)
    prepare_source(context, settings, client.app.state.objects, None, data['payload'], tmp_path)
    extracted = client.get(f"/api/sources/{source['id']}", headers=headers('alice')).json()
    assert extracted['state'] == 'needs_confirmation' and not extracted['confirmed']
    assert extracted['evidence'][0]['method'] == 'gemini-derived-notes'
    correction = {'expected_version': extracted['version'], 'evidence': extracted['evidence'],
                  'confirm': True, 'note': 'Author checked fixture.'}
    assert client.put(f"/api/sources/{source['id']}/preview", headers=headers('alice'), json=correction).status_code == 409
    correction['evidence'][0]['uncertainty'] = []
    assert client.put(f"/api/sources/{source['id']}/preview", headers=headers('alice'), json=correction).status_code == 200
    call = provider.__enter__.return_value.models.generate_content.call_args.kwargs
    assert call['model'] == 'fixture-vision'
    assert call['contents'][0].file_data.file_uri == source['original_url']
    for accessible, duration, code in [(False, 10, 'SOURCE_UNAVAILABLE'), (True, 3601, 'SOURCE_BATCH_REQUIRED')]:
        provider.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps({**response_body, 'accessible': accessible, 'duration_seconds': duration}))
        with pytest.raises(GenerationError) as error:
            extract_vision(settings, youtube_url=source['original_url'])
        assert error.value.code == code
