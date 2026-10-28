"""Rolling adaptive teaching: deterministic metrics and synthetic provider fixtures."""
from sqlalchemy import select
import pytest

from server.database import Block, Curriculum, Job
from server.learning.adaptation import understanding
from server.lessons.authoring import StructuredAuthor
from server.platform_settings import PlatformSettings
from server.worker.queue import enqueue
from server.worker.queue import JobContext, claim
from tests.test_platform import (answer_body, complete_adaptive_fixture, finish_clip, headers,
                                 platform, seed_lesson, start)  # noqa: F401


def objectives(count=6):
    return [{'id': f'o{i}', 'title': f'Concept {i}', 'prerequisites': []} for i in range(count)]


def evidence(*, passed=True, hints=0, attempts=1, solution=False):
    return {'first_attempt_passed': passed, 'first_score': float(passed), 'latest_score': float(passed),
            'status': 'unresolved' if solution else 'assisted' if hints else 'passed' if passed else 'needs_revision',
            'hints_used': hints, 'attempts': attempts, 'solution_shown': solution}


def test_metric_is_provisional_and_requires_multiple_independent_successes():
    assert understanding({}, objectives())['level'] == 'balanced'
    assert understanding({'o0': evidence()}, objectives())['level'] == 'balanced'
    strong = understanding({'o0': evidence(), 'o1': evidence()}, objectives())
    assert strong['level'] == 'challenge' and strong['score'] > 80
    assert strong['confidence'] == 'provisional'
    weak = understanding({'o0': evidence(passed=False)}, objectives())
    assert weak['level'] == 'supportive' and weak['score'] < 50


def test_hints_retries_shown_solutions_and_partial_scores_change_the_signal():
    items = objectives()
    clean = understanding({'o0': evidence(), 'o1': evidence()}, items)
    hints = understanding({'o0': evidence(hints=1), 'o1': evidence(hints=2)}, items)
    retry = evidence(passed=False, attempts=2); retry.update(status='passed', latest_score=1)
    retried = understanding({'o0': retry}, items)
    shown = understanding({'o0': evidence(solution=True)}, items)
    assert hints['score'] < clean['score'] and hints['level'] != 'challenge'
    assert retried['score'] < understanding({'o0': evidence()}, items)['score']
    assert shown['score'] < 50
    partial = evidence(passed=False); partial.update(first_score=.5, latest_score=.5)
    assert understanding({'o0': partial}, items)['score'] > understanding({'o0': evidence(passed=False)}, items)['score']


def test_first_three_are_normal_and_assessment_one_commits_background_block_four(platform):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=6)
    with factory.begin() as db:
        for block in db.scalars(select(Block).where(Block.curriculum_id == version, Block.objective_id.in_(['o1', 'o2']))):
            block.state = 'planned'
    session = start(client, version)
    with factory() as db:
        jobs = db.scalars(select(Job)).all()
        assert {job.payload['objective_id'] for job in jobs} == {'o1', 'o2'}
        assert all(job.payload['profile'] == 'normal' for job in jobs)
    # Free admission capacity after the two synthetic startup jobs complete.
    with factory.begin() as db:
        for job in db.scalars(select(Job)):
            job.state = 'completed'
        for block in db.scalars(select(Block).where(Block.curriculum_id == version)):
            block.state = 'ready'
    session = finish_clip(client, session)
    response = client.post('/api/attempts', headers=headers('alice'), json=answer_body(session))
    assert response.status_code == 202
    with factory() as db:
        adaptive = [job for job in db.scalars(select(Job)) if job.payload.get('profile') == 'adapted']
        assert len(adaptive) == 1
        job = adaptive[0]
        assert job.payload['objective_id'] == 'o3' and job.payload['adaptation']['assessment_number'] == 1
        assert job.state == 'queued' and job.priority == 2  # Route advancement must not cancel it.
        assert session['id'] in job.consumers


def test_normal_ready_blocks_do_not_bypass_adaptation_and_mapping_keeps_moving(platform):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=6)
    session = start(client, version)
    for index in range(3):
        session = finish_clip(client, session)
        response = client.post('/api/attempts', headers=headers('alice'), json=answer_body(session))
        assert response.status_code == 202
        session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
    assert session['objective_id'] == 'o3' and session['state'] == 'waiting_for_block'
    with factory() as db:
        jobs = [job for job in db.scalars(select(Job)) if job.payload.get('profile') == 'adapted']
        assert {(job.payload['objective_id'], job.payload['adaptation']['assessment_number']) for job in jobs} == {('o3', 1), ('o4', 2), ('o5', 3)}
        assert all(job.state == 'queued' for job in jobs)
        assert db.get(Job, session['continuation_job_id']).payload['adaptation']['level'] == 'balanced'
    complete_adaptive_fixture(factory, session)
    session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
    assert session['state'] == 'playing' and session['adaptivity']['current_teaching']['assessment_number'] == 1
    with factory() as db:
        assert db.get(Block, session['selected_block_id']).profile == 'adapted'


def test_queue_full_preserves_plan_and_poll_retries_without_duplicate_jobs(platform):
    client, factory, ids = platform
    client.app.state.settings.max_jobs_per_user = 1
    _, version = seed_lesson(factory, ids, count=5)
    session = finish_clip(client, start(client, version))
    with factory.begin() as db:
        blocker = enqueue(db, client.app.state.settings, ids['alice'], 'source', {'fixture': True}, scope='fixture:capacity')
        blocker_id = blocker.id
    assert client.post('/api/attempts', headers=headers('alice'), json=answer_body(session)).status_code == 202
    session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
    assert session['state'] == 'playing' and session['evidence']['o3']['adaptive_plan']
    frozen_hash = session['evidence']['o3']['adapted_hash']
    with factory.begin() as db:
        db.get(Job, blocker_id).state = 'completed'
    progress = client.patch(f"/api/sessions/{session['id']}/progress", headers=headers('alice'), json={
        'expected_revision': session['revision'], 'route_revision': session['route_revision'],
        'block_id': session['selected_block_id'], 'clip': 0, 'offset': 1, 'ended': False})
    assert progress.status_code == 200, progress.text
    for _ in range(3):
        session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
    with factory() as db:
        jobs = [job for job in db.scalars(select(Job)) if job.payload.get('profile') == 'adapted']
        assert len(jobs) == 1 and jobs[0].payload['context_hash'] == frozen_hash


def test_retries_update_learning_signal_without_regenerating_the_frozen_future_video(platform):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=5)
    session = finish_clip(client, start(client, version))
    client.post('/api/attempts', headers=headers('alice'), json=answer_body(session, 'no'))
    session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
    frozen = session['evidence']['o3']['adapted_hash']
    session = finish_clip(client, session)
    client.post('/api/attempts', headers=headers('alice'), json=answer_body(session))
    session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
    assert session['evidence']['o0']['latest_score'] == 1 and session['evidence']['o0']['first_score'] == 0
    assert session['evidence']['o3']['adapted_hash'] == frozen
    with factory() as db:
        assert len([job for job in db.scalars(select(Job)) if job.payload.get('profile') == 'adapted']) == 1


def test_teaching_plan_reaches_the_model_prompt():
    author = StructuredAuthor(PlatformSettings(text_model='fixture', verifier_model='fixture'), None)
    captured = {}
    author.ask = lambda stage, model, contract, task, data, **kwargs: captured.update(task=task, data=data)
    objective = {**objectives(1)[0], 'description': 'A complete fixture concept', 'evidence': [], 'worked_example': 'A small fixture', 'visual_approach': 'A process'}
    plan = understanding({'o0': evidence(passed=False)}, objectives())
    author._author_draft({'objectives': [objective]}, objective, [], 'adapted', None, 0, None, [], plan)
    assert captured['data']['teaching_plan']['level'] == 'supportive'
    assert 'smaller examples' in captured['task'] and 'Never lower coverage' in captured['task']


def test_classroom_keeps_reviewed_routes_without_live_adaptive_generation(platform):
    client, factory, ids = platform
    course = client.post('/api/courses', headers=headers('teacher'), json={'title': 'Reviewed fixture class'}).json()
    _, version = seed_lesson(factory, ids, owner='teacher', course_id=course['id'], count=5)
    packet = client.get(f'/api/reviews/{version}', headers=headers('teacher')).json()
    checks = {'expected_fingerprint': packet['fingerprint'], 'coverage': True, 'factual': True, 'assessments': True, 'media': True}
    assert client.post(f'/api/reviews/{version}/approve', headers=headers('teacher'), json=checks).status_code == 200
    assert client.post(f'/api/reviews/{version}/publish', headers=headers('teacher')).status_code == 200
    assigned = client.post(f"/api/courses/{course['id']}/assignments", headers=headers('teacher'), json={'curriculum_id': version}).json()
    code = client.post(f"/api/courses/{course['id']}/enrollment-code", headers=headers('teacher')).json()['code']
    client.post('/api/courses/join', headers=headers('alice'), json={'code': code})
    session = finish_clip(client, start(client, version, assignment_id=assigned['id']))
    client.post('/api/attempts', headers=headers('alice'), json=answer_body(session, 'no'))
    session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
    assert session['adaptivity']['mode'] == 'reviewed_classroom' and not session['adaptivity']['planned']
    with factory() as db:
        assert db.get(Block, session['selected_block_id']).profile == 'recap'
        assert not db.scalars(select(Job).where(Job.kind == 'block')).all()


@pytest.mark.parametrize('classroom', [False, True])
def test_bulk_preparation_limits_independent_work_to_three_initial_blocks(platform, monkeypatch, tmp_path, classroom):
    from server.worker.tasks import prepare_whole_lesson
    client, factory, ids = platform
    course = client.post('/api/courses', headers=headers('teacher'), json={'title': 'Fixture course'}).json() if classroom else None
    owner = 'teacher' if classroom else 'alice'
    _, version = seed_lesson(factory, ids, owner=owner, course_id=course['id'] if course else None, count=6)
    with factory.begin() as db:
        enqueue(db, client.app.state.settings, ids[owner], 'prepare_lesson', {'curriculum_id': version}, scope='fixture:initial-window')
    called = []
    monkeypatch.setattr('server.worker.tasks.prepare_block', lambda context, settings, objects, runner, payload, folder: called.append(payload['objective_id']))
    context = JobContext(factory, claim(factory))
    prepare_whole_lesson(context, client.app.state.settings, None, None, {'curriculum_id': version}, tmp_path)
    assert called == [f'o{i}' for i in range(6 if classroom else 3)]
