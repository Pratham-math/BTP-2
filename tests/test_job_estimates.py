"""ETA ranges are advisory and never substitute for successful generation."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from server.database import Job
from server.worker.estimates import estimate, timing_profile
from server.worker.queue import JobContext, claim, enqueue
from tests.test_platform import headers, platform, seed_lesson, start  # noqa: F401


def job(**values):
    return SimpleNamespace(kind='quick_lesson', state='running', lease_until=2100,
                           result={'_timing': {'started_at': 1000, 'profile': timing_profile()}}, **values)


def test_initial_estimate_counts_down_and_excludes_queue_wait():
    item = job()
    initial, later = estimate(item, [], now=1100), estimate(item, [], now=1200)
    assert initial['basis'] == 'rough_initial_range'
    assert initial['upper_seconds'] - later['upper_seconds'] == 100
    item.state = 'queued'
    value = estimate(item, [], now=1200)
    assert value['upper_seconds'] == 2400 and not value['queue_wait_included']


def test_estimate_uses_only_clean_compatible_completed_runs():
    item = job()
    history = [SimpleNamespace(kind=item.kind, state='completed', result={'_timing': {
        'profile': timing_profile(), 'run_seconds': seconds, 'units': 1, 'clean_run': True}}) for seconds in (300, 400, 500)]
    incompatible = SimpleNamespace(kind=item.kind, state='completed', result={'_timing': {
        'profile': 'different-provider', 'run_seconds': 99999, 'clean_run': True}})
    result = estimate(item, [*history, incompatible], now=1100)
    assert result['basis'] == 'recent_completed_runs' and result['sample_count'] == 3
    assert result['lower_seconds'] == 100 and result['upper_seconds'] == 600
    history[0].result['_timing']['clean_run'] = False
    assert estimate(item, history, now=1100)['basis'] == 'rough_initial_range'


@pytest.mark.parametrize('state', ['completed', 'failed', 'cancelled', 'waiting_for_input', 'waiting_for_review'])
def test_stopped_or_action_required_jobs_have_no_eta(state):
    item = job(); item.state = state
    assert estimate(item, [], now=1100)['upper_seconds'] is None


def test_expired_lease_and_overrun_do_not_show_fake_countdown():
    item = job(); item.lease_until = 900
    assert estimate(item, [], now=1100)['status'] == 'recovering'
    item.lease_until = 9999
    value = estimate(item, [], now=4000)
    assert value['status'] == 'taking_longer' and value['upper_seconds'] is None


def test_claim_and_finish_record_private_timing_and_scope_job_views(platform):
    client, factory, ids = platform
    with factory.begin() as db:
        queued = enqueue(db, client.app.state.settings, ids['alice'], 'source', {'source_id': 'fixture'}, scope='fixture')
        identifier = queued.id
    context = JobContext(factory, claim(factory, queue='generation'))
    context.finish({'source_id': 'fixture'})
    with factory() as db:
        timing = db.get(Job, identifier).result['_timing']
        assert timing['run_seconds'] >= 0 and timing['clean_run']
    result = client.get(f'/api/jobs/{identifier}', headers=headers('alice')).json()
    assert result['result'] == {'source_id': 'fixture'} and result['eta']['status'] == 'completed'
    assert '_timing' not in str(result)
    assert client.get(f'/api/jobs/{identifier}', headers=headers('bob')).status_code == 404
    assert client.get('/api/jobs', headers=headers('bob')).json() == []


def test_session_summary_exposes_scope_and_progress_without_keys(platform):
    client, factory, ids = platform
    _, curriculum = seed_lesson(factory, ids)
    created = start(client, curriculum)
    summary = client.get('/api/sessions', headers=headers('alice')).json()[0]
    assert summary['id'] == created['id'] and summary['curriculum_id'] == curriculum
    assert summary['course_id'] is None and summary['assignment_id'] is None
    assert summary['total_objectives'] == 2 and summary['covered_objectives'] == summary['passed_objectives'] == 0
    assert 'key' not in summary and client.get('/api/sessions', headers=headers('bob')).json() == []
