"""Explicit laptop-demo behavior; this is not a security-isolation test."""
from fastapi.testclient import TestClient
import pytest

from server.assessment.runner import JudgeRunner, configured_runner
from server.database import Job
from server.local_services import LocalRunner
from server.platform import create_app
from server.platform_settings import PlatformSettings
from server.providers.base import GenerationError
from server.worker.queue import claim
from server.worker.__main__ import execute
from tests.test_platform import headers, platform, python_checkpoint  # noqa: F401


def settings():
    return PlatformSettings(profile='local', local_demo_python=True)


def test_demo_runner_requires_explicit_opt_in_and_is_never_selected_in_production():
    for value in [PlatformSettings(profile='local'), PlatformSettings(profile='production', local_demo_python=True)]:
        assert not value.demo_runner and not value.checks()['python_runner']
        runner = configured_runner(value)
        assert isinstance(runner, JudgeRunner)
        runner.close()
        with pytest.raises(GenerationError, match='explicit'):
            LocalRunner(value).run('print(1)', '')
    assert isinstance(configured_runner(settings()), LocalRunner)


def test_demo_config_is_honest_and_rejects_non_loopback_clients():
    app = create_app(settings())
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        config = client.get('/api/config').json()
        assert config['python_enabled'] and config['runner_mode'] == 'local_demo' and not config['runner_isolated']
        ready = client.get('/api/ready').json()
        assert ready['checks']['python_runner'] and not ready['runner_isolated']
        assert client.get('/api/config', headers={'X-Forwarded-For': '203.0.113.9'}).status_code == 403
    with TestClient(create_app(PlatformSettings(profile='local', local_demo_python=True, tunnel_demo_python=True)), client=('127.0.0.1', 50000)) as client:
        assert client.get('/api/config', headers={'X-Forwarded-For': '203.0.113.9'}).json()['python_enabled']
    with TestClient(app, client=('192.0.2.1', 50000)) as client:
        assert client.get('/api/config').status_code == 403


def test_demo_runner_bounds_time_and_output_and_filters_environment(tmp_path, monkeypatch):
    monkeypatch.setattr('server.local_services.LOCAL_TEMP', tmp_path)
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-secret-must-not-be-inherited')
    runner = LocalRunner(settings())
    assert runner.run("import os; print(os.getenv('GEMINI_API_KEY', 'missing'))", '') == (True, 'missing\n')
    assert not runner.run("print('x' * 70000)", '')[0]
    runner.timeout_seconds = .2
    assert not runner.run('while True: pass', '')[0]


def test_demo_results_survive_runner_recreation(tmp_path, monkeypatch):
    monkeypatch.setattr('server.local_services.LOCAL_TEMP', tmp_path)
    key = {'tests': [{'stdin': '2 3', 'expected': '5', 'category': 'sum'}], 'hints': ['Add them'], 'explanation': 'Read two integers and add.'}
    tokens = LocalRunner(settings()).submit('print(sum(map(int, input().split())))', key)
    assert LocalRunner(settings()).poll(tokens, key)['passed']
    with pytest.raises(GenerationError):
        LocalRunner(settings()).poll(['../outside'], key)


def test_python_checkpoint_is_graded_by_local_demo_worker(platform):
    original_client, factory, ids = platform
    app = original_client.app
    app.state.settings.profile = 'local'
    app.state.settings.local_demo_python = True
    app.state.runner.close()
    app.state.runner = configured_runner(app.state.settings)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        session = python_checkpoint(client, factory, ids)
        app.state.runner = configured_runner(app.state.settings)
        response = client.post('/api/attempts', headers=headers('alice'), json={
            'session_id': session['id'], 'assessment_id': session['question']['id'],
            'route_revision': session['route_revision'], 'expected_revision': session['revision'],
            'idempotency_key': 'local-demo-end-to-end', 'answer': {'code': 'print(2)'}})
        assert response.status_code == 202, response.text
        data = claim(factory, queue='grading')
        execute(factory, app.state.settings, data, objects=app.state.objects)
        with factory() as db:
            assert db.get(Job, data['id']).state == 'completed'
        session = client.get(f"/api/sessions/{session['id']}", headers=headers('alice')).json()
        assert session['evidence']['o0']['status'] == 'passed'
