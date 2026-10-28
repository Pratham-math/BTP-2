"""Lesson removal, permanent teacher-only codes and voluntary departures."""
import hashlib
import pytest
from sqlalchemy import select

from server.database import Course, Curriculum, Job, LearningSession, Membership, Source
from server.providers.base import GenerationError
from server.worker.queue import JobContext, claim, enqueue
from tests.test_platform import headers, platform, seed_lesson, start  # noqa: F401


def course_fixture(client, factory, ids):
    course = client.post('/api/courses', headers=headers('teacher'), json={'title': 'Permanent code fixture'}).json()
    code = client.get(f"/api/courses/{course['id']}/enrollment-code", headers=headers('teacher')).json()['code']
    assert client.post('/api/courses/join', headers=headers('alice'), json={'code': code}).status_code == 200
    _, version = seed_lesson(factory, ids, owner='teacher', course_id=course['id'])
    packet = client.get(f'/api/reviews/{version}', headers=headers('teacher')).json()
    body = {'expected_fingerprint': packet['fingerprint'], 'coverage': True, 'factual': True, 'assessments': True, 'media': True}
    assert client.post(f'/api/reviews/{version}/approve', headers=headers('teacher'), json=body).status_code == 200
    assert client.post(f'/api/reviews/{version}/publish', headers=headers('teacher')).status_code == 200
    assigned = client.post(f"/api/courses/{course['id']}/assignments", headers=headers('teacher'), json={'curriculum_id': version}).json()
    return course, code, version, assigned


def test_permanent_code_survives_reads_and_pausing_and_is_teacher_only(platform):
    client, _, _ = platform
    course = client.post('/api/courses', headers=headers('teacher'), json={'title': 'Stable enrollment'}).json()
    path = f"/api/courses/{course['id']}/enrollment-code"
    initial = client.get(path, headers=headers('teacher')).json()
    assert initial['enabled'] and len(initial['code']) >= 12
    assert client.post(path, headers=headers('teacher')).json()['code'] == initial['code']
    assert client.post('/api/courses/join', headers=headers('alice'), json={'code': initial['code']}).status_code == 200
    for user in ('alice', 'bob', 'admin'):
        assert client.get(path, headers=headers(user)).status_code == 404
        assert client.post(path, headers=headers(user)).status_code == 404
        assert client.delete(path, headers=headers(user)).status_code == 404
    assert initial['code'] not in str(client.get('/api/courses', headers=headers('alice')).json())
    client.delete(path, headers=headers('teacher'))
    assert client.get(path, headers=headers('teacher')).json() == {**initial, 'enabled': False}
    assert client.post('/api/courses/join', headers=headers('bob'), json={'code': initial['code']}).status_code == 404
    assert client.post(path, headers=headers('teacher')).json()['code'] == initial['code']
    assert client.post('/api/courses/join', headers=headers('bob'), json={'code': initial['code']}).status_code == 200


def test_legacy_hash_code_remains_valid_when_a_visible_permanent_code_is_allocated(platform):
    client, factory, ids = platform
    legacy = 'fixture-legacy-last-code'
    with factory.begin() as db:
        course = Course(owner_id=ids['teacher'], title='Legacy course fixture',
            enrollment_hash=hashlib.sha256(legacy.encode()).hexdigest(), enrollment_enabled=True)
        db.add(course); db.flush(); identifier = course.id
    path = f'/api/courses/{identifier}/enrollment-code'
    permanent = client.get(path, headers=headers('teacher')).json()['code']
    assert client.get(path, headers=headers('teacher')).json()['code'] == permanent
    for user, code in [('alice', legacy), ('bob', permanent)]:
        assert client.post('/api/courses/join', headers=headers(user), json={'code': code}).status_code == 200


def test_leaving_revokes_access_but_keeps_history_and_allows_rejoining(platform):
    client, factory, ids = platform
    course, code, version, assignment = course_fixture(client, factory, ids)
    session = start(client, version, assignment_id=assignment['id'])
    path = f"/api/courses/{course['id']}/leave"
    assert client.post(path, headers=headers('teacher')).status_code == 409
    assert client.post(path, headers=headers('bob')).status_code == 404
    assert client.post(path, headers=headers('alice')).status_code == 200
    assert client.get('/api/courses', headers=headers('alice')).json() == []
    assert client.get(f"/api/courses/{course['id']}/assignments", headers=headers('alice')).status_code == 404
    assert client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).status_code == 403
    with factory() as db:
        assert db.get(LearningSession, session['id']) is not None
        membership = db.scalar(select(Membership).where(Membership.user_id == ids['alice']))
        assert membership.left_voluntarily and not membership.active
        membership_id = membership.id
    assert client.patch(f"/api/courses/{course['id']}/members/{membership_id}?active=true", headers=headers('teacher')).status_code == 409
    assert client.post('/api/courses/join', headers=headers('alice'), json={'code': code}).status_code == 200
    restored = start(client, version, assignment_id=assignment['id'])
    assert restored['id'] == session['id']
    assert client.get(f"/api/reports/courses/{course['id']}", headers=headers('teacher')).json()[0]['session_id'] == session['id']


def test_revoked_membership_cannot_be_converted_into_a_voluntary_leave(platform):
    client, factory, ids = platform
    course, code, _, _ = course_fixture(client, factory, ids)
    member = client.get(f"/api/courses/{course['id']}/members", headers=headers('teacher')).json()[0]
    client.patch(f"/api/courses/{course['id']}/members/{member['id']}?active=false", headers=headers('teacher'))
    assert client.post(f"/api/courses/{course['id']}/leave", headers=headers('alice')).status_code == 404
    assert client.post('/api/courses/join', headers=headers('alice'), json={'code': code}).status_code == 403


def test_lesson_delete_hides_sessions_and_jobs_and_fences_the_worker(platform):
    client, factory, ids = platform
    lesson_id, version = seed_lesson(factory, ids)
    session = start(client, version)
    with factory.begin() as db:
        job = enqueue(db, client.app.state.settings, ids['alice'], 'block',
            {'curriculum_id': version, 'objective_id': 'o1', 'profile': 'normal', 'context_hash': 'base'}, scope='fixture:delete')
        job_id = job.id
    context = JobContext(factory, claim(factory))
    assert client.delete(f'/api/lessons/{lesson_id}', headers=headers('bob')).status_code == 404
    response = client.delete(f'/api/lessons/{lesson_id}', headers=headers('alice'))
    assert response.status_code == 200 and response.json()['deleted']
    for path in ('/api/lessons', '/api/sessions', '/api/reports/me', '/api/jobs'):
        assert client.get(path, headers=headers('alice')).json() == []
    assert client.get(f'/api/lessons/versions/{version}', headers=headers('alice')).status_code == 404
    assert client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).status_code == 409
    assert client.post(f'/api/jobs/{job_id}/retry', headers=headers('alice')).status_code == 409
    with pytest.raises(GenerationError):
        context.check()


def test_classroom_lesson_delete_removes_assignments_and_retains_grade_history(platform):
    client, factory, ids = platform
    course, _, version, assignment = course_fixture(client, factory, ids)
    session = start(client, version, assignment_id=assignment['id'])
    with factory() as db:
        lesson_id = db.get(Curriculum, version).lesson_id
    assert client.delete(f'/api/lessons/{lesson_id}', headers=headers('alice')).status_code == 404
    assert client.delete(f'/api/lessons/{lesson_id}', headers=headers('teacher')).status_code == 200
    assert client.get(f"/api/courses/{course['id']}/assignments", headers=headers('alice')).json() == []
    assert client.get(f"/api/reports/courses/{course['id']}", headers=headers('teacher')).json()[0]['session_id'] == session['id']
