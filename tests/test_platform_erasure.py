"""Disposable erasure fixtures; no real account or cloud object is deleted."""
from types import SimpleNamespace
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from server.database import (Assessment, Asset, Assignment, Attempt, Block, Curriculum, Job, LearningSession,
    Membership, Profile, Source, SourceVersion)
from server.erasure import delete_auth_identity, erase_account, erasure_keys, purge_worker_cache
from server.providers.base import GenerationError
from server.worker.queue import JobContext, claim
from test_platform import platform, headers, seed_lesson, start, finish_clip, answer_body


def request(client, name='alice'):
    response = client.post('/api/me/erasure', headers=headers(name), json={'confirmation': 'DELETE'})
    assert response.status_code == 202, response.text
    # Skip the production two-minute worker-drain grace in disposable fixtures.
    with client.app.state.db.begin() as db:
        db.get(Job, response.json()['job_id']).created_at = time.time() - 121
    return response.json()


def objects_fixture(delete):
    return SimpleNamespace(delete=delete, list_prefix=lambda prefix: [])


def test_erasure_requires_confirmation_and_immediately_blocks_all_account_access(platform):
    client, factory, ids = platform
    assert client.post('/api/me/erasure', headers=headers('alice'), json={'confirmation': 'wrong'}).status_code == 422
    result = request(client)
    assert result['application_access'] == 'disabled'
    assert client.get('/api/me', headers=headers('alice')).status_code == 403
    assert client.post('/api/sources', headers=headers('alice'), json={'title': 'Should fail', 'kind': 'text', 'text': 'No post-erasure writes'}).status_code == 403
    with factory.begin() as db:
        profile = db.get(Profile, ids['alice'])
        assert not profile.active and profile.email == '' and profile.display_name == 'Deleted learner'
    assert claim(factory, queue='generation') is None
    assert claim(factory, queue='grading') is None
    assert claim(factory, queue='maintenance')['kind'] == 'erase_account'


def test_last_administrator_cannot_remove_the_only_operational_owner(platform):
    client, _, _ = platform
    assert client.post('/api/me/erasure', headers=headers('admin'), json={'confirmation': 'DELETE'}).status_code == 409
    assert client.get('/api/me', headers=headers('admin')).status_code == 200


def test_classroom_completion_is_anonymized_and_retained_while_answers_are_removed(platform, monkeypatch, tmp_path):
    client, factory, ids = platform
    course = client.post('/api/courses', headers=headers('teacher'), json={'title': 'Fixture classroom'}).json()
    code = client.post(f"/api/courses/{course['id']}/enrollment-code", headers=headers('teacher')).json()['code']
    client.post('/api/courses/join', headers=headers('alice'), json={'code': code})
    _, version = seed_lesson(factory, ids, owner='teacher', course_id=course['id'], count=1)
    with factory.begin() as db:
        db.get(Curriculum, version).publication = 'published'
        assignment = Assignment(course_id=course['id'], curriculum_id=version)
        db.add(assignment); db.flush(); assignment_id = assignment.id
    session = finish_clip(client, start(client, version, assignment_id=assignment_id))
    client.post('/api/attempts', headers=headers('alice'), json=answer_body(session))
    request(client)
    context = JobContext(factory, claim(factory, queue='maintenance'))
    monkeypatch.setattr('server.erasure.delete_auth_identity', lambda *args: None)
    erase_account(context, client.app.state.settings, objects_fixture(lambda key: None), None, context.claim['payload'], tmp_path)
    with factory.begin() as db:
        saved = db.get(LearningSession, session['id'])
        assert saved.state == 'withdrawn' and saved.evidence['o0']['status'] == 'passed'
        assert saved.position == {}
        attempt = db.scalar(select(Attempt).where(Attempt.user_id == ids['alice']))
        assert attempt.answer == {} and attempt.result['passed'] is True
        assert not db.scalar(select(Membership).where(Membership.user_id == ids['alice'])).active
    report = client.get(f"/api/reports/courses/{course['id']}", headers=headers('teacher')).json()
    assert report[0]['learner'] == 'Deleted learner' and report[0]['evidence']['o0']['status'] == 'passed'


def test_private_cleanup_retains_shared_classroom_assets_and_tracks_auth_separately(platform, monkeypatch, tmp_path):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=1)
    session = start(client, version)
    # Forking into a classroom can retain a reference to the same valid object.
    with factory.begin() as db:
        original = db.scalar(select(Asset).join(Block, Block.id == Asset.block_id).where(Block.curriculum_id == version, Asset.kind == 'clip'))
        shared_key = original.object_key
    _, classroom_version = seed_lesson(factory, ids, owner='teacher', count=1)
    with factory.begin() as db:
        classroom = db.scalar(select(Block).where(Block.curriculum_id == classroom_version).limit(1))
        db.add(Asset(block_id=classroom.id, kind='shared-fixture', position=8, object_key=shared_key, checksum='a'*64, duration=1))
    request(client)
    context = JobContext(factory, claim(factory, queue='maintenance'))
    deleted = []
    objects = objects_fixture(deleted.append)
    monkeypatch.delenv('SUPABASE_AUTH_ADMIN_KEY', raising=False)
    with pytest.raises(GenerationError) as failure:
        erase_account(context, client.app.state.settings, objects, None, context.claim['payload'], tmp_path)
    assert failure.value.code == 'AUTH_ERASURE_NOT_CONFIGURED'
    assert shared_key not in deleted
    with factory.begin() as db:
        assert db.get(Curriculum, version).blueprint == {}
        assert db.get(Curriculum, classroom_version).blueprint != {}
        assert db.get(LearningSession, session['id']).state == 'erased'
        assert all(x.private == {} for x in db.scalars(select(Assessment).where(Assessment.curriculum_id == version)))
    # A retry after a credential outage does not recalculate an empty object
    # ledger or lose evidence of the already-completed application cleanup.
    before = list(deleted)
    monkeypatch.setattr('server.erasure.delete_auth_identity', lambda *args: None)
    result = erase_account(context, client.app.state.settings, objects, None, context.claim['payload'], tmp_path)
    assert result['auth_identity_erased'] and deleted == before


def test_object_deletion_failure_does_not_confirm_private_data_erasure(platform, tmp_path):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=1)
    request(client)
    context = JobContext(factory, claim(factory, queue='maintenance'))
    def fail(key):
        raise GenerationError('STORAGE_FAILED', 'Controlled fixture storage outage')
    with pytest.raises(GenerationError, match='outage'):
        erase_account(context, client.app.state.settings, objects_fixture(fail), None, context.claim['payload'], tmp_path)
    assert context.saved('application_erased', {'user_id': ids['alice'], 'policy': 'anonymize_classroom', 'version': 1}) is None
    with factory.begin() as db:
        assert db.get(Curriculum, version).blueprint


def test_cache_cleanup_targets_only_an_exact_owned_job_directory(tmp_path):
    identifier = str(uuid4())
    root = tmp_path / 'worker-cache'
    target = root / identifier
    target.mkdir(parents=True)
    (target / 'fixture-private.txt').write_text('Disposable fixture only')
    unrelated = root / str(uuid4())
    unrelated.mkdir()
    purge_worker_cache(identifier, root)
    assert not target.exists() and unrelated.exists()
    with pytest.raises(ValueError):
        purge_worker_cache('../', root)


def test_object_inventory_includes_orphan_uploads_but_excludes_retained_classroom_namespaces():
    inventory = {'keys': ['lessons/private/attached.mp4'], 'source_prefix': 'sources/owner/',
        'keep_prefixes': ['sources/owner/classroom/'], 'keep_exact': [], 'lesson_prefixes': ['lessons/private/'],
        'retained_keys': ['lessons/private/shared.mp4']}
    values = {'sources/owner/': ['sources/owner/orphan/original.pdf', 'sources/owner/classroom/kept.png'],
        'lessons/private/': ['lessons/private/attached.mp4', 'lessons/private/unattached.mp4', 'lessons/private/shared.mp4']}
    keys = erasure_keys(inventory, SimpleNamespace(list_prefix=lambda prefix: values[prefix]))
    assert keys == ['lessons/private/attached.mp4', 'lessons/private/unattached.mp4', 'sources/owner/orphan/original.pdf']


def test_erasure_waits_for_cancelled_worker_shutdown_acknowledgment(platform, tmp_path):
    client, factory, ids = platform
    with factory.begin() as db:
        old = Job(owner_id=ids['alice'], kind='source', state='running', fence=1,
            lease_until=time.time()+90, dedup_key='fixture-running-job', payload={})
        db.add(old); db.flush(); old_id = old.id
    request(client)
    context = JobContext(factory, claim(factory, queue='maintenance'))
    with pytest.raises(GenerationError) as failure:
        erase_account(context, client.app.state.settings, objects_fixture(lambda key: None), None, context.claim['payload'], tmp_path)
    assert failure.value.code == 'ERASURE_WORKERS_NOT_STOPPED'
    assert context.saved('application_erased', {'user_id': ids['alice'], 'policy': 'anonymize_classroom', 'version': 1}) is None


def test_cancelled_worker_acknowledges_only_its_exact_lost_fence_on_exit(platform, monkeypatch, tmp_path):
    from server.worker.__main__ import execute, HANDLERS
    client, factory, ids = platform
    with factory.begin() as db:
        job = Job(owner_id=ids['alice'], kind='ack_fixture', dedup_key='fixture-ack', payload={})
        db.add(job); db.flush(); identifier = job.id
    selected = claim(factory, owner_id=ids['alice'])
    def handler(context, *args):
        with factory.begin() as db:
            job = db.get(Job, identifier)
            job.state, job.fence, job.lease_until = 'cancelled', job.fence + 1, None
        context.check()
    monkeypatch.setitem(HANDLERS, 'ack_fixture', handler)
    monkeypatch.setattr('server.worker.__main__.PROJECT_DIR', tmp_path)
    execute(factory, client.app.state.settings, selected, objects=objects_fixture(lambda key: None), runner=SimpleNamespace(close=lambda: None))
    with factory.begin() as db:
        job = db.get(Job, identifier)
        assert job.state == 'cancelled' and job.result['worker_stopped'] is True


def test_only_admin_can_view_and_retry_blocked_cleanup(platform):
    client, factory, _ = platform
    result = request(client)
    assert client.get('/api/admin/erasures', headers=headers('bob')).status_code == 403
    with factory.begin() as db:
        db.get(Job, result['job_id']).state = 'waiting_for_input'
    rows = client.get('/api/admin/erasures', headers=headers('admin')).json()
    assert rows[0]['id'] == result['job_id']
    assert client.post(f"/api/admin/erasures/{result['job_id']}/retry", headers=headers('bob')).status_code == 403
    assert client.post(f"/api/admin/erasures/{result['job_id']}/retry", headers=headers('admin')).status_code == 202


@pytest.mark.parametrize('status,body,accepted', [(200, {}, True), (404, {'code': 'user_not_found'}, True),
    (404, {'error_code': 'user_not_found'}, True), (404, {}, False), (403, {}, False)])
def test_auth_cleanup_requires_confirmed_server_response(status, body, accepted, monkeypatch):
    monkeypatch.setenv('SUPABASE_AUTH_ADMIN_KEY', 'fixture-admin-only-key')
    def respond(url, **kwargs):
        assert kwargs['headers']['apikey'] == 'fixture-admin-only-key'
        return httpx.Response(status, json=body)
    monkeypatch.setattr(httpx, 'delete', respond)
    settings = SimpleNamespace(supabase_url='https://fixture.supabase.co')
    user_id = str(uuid4())
    if accepted:
        delete_auth_identity(settings, user_id)
    else:
        with pytest.raises(GenerationError):
            delete_auth_identity(settings, user_id)
