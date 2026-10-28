"""The read-only runner probe must not execute code or imply host isolation."""
import httpx
import pytest

from scripts.check_runner import inspect_runner
from server.platform_settings import PlatformSettings


def test_runner_probe_discovers_python_and_checks_configuration():
    requests = []
    def handle(request):
        requests.append(request)
        if not request.headers.get('X-Auth-Token'):
            return httpx.Response(401)
        if request.url.path == '/languages':
            return httpx.Response(200, json=[{'id': 42, 'name': 'Python 3 (fixture)'}, {'id': 1, 'name': 'C (fixture)'}])
        return httpx.Response(200, json={'enable_network': False, 'allow_enable_network': False,
            'max_cpu_time_limit': 2, 'max_wall_time_limit': 5, 'max_memory_limit': 131072,
            'max_stack_limit': 8192, 'max_max_processes_and_or_threads': 1, 'max_max_file_size': 64})
    settings = PlatformSettings(runner_url='https://runner.example.test', runner_token='fixture-token', runner_language_id=42)
    with httpx.Client(transport=httpx.MockTransport(handle), headers={'X-Auth-Token': settings.runner_token}) as client:
        result = inspect_runner(settings, client)
    assert result['configuration_compatible']
    assert result['python_languages'] == [{'id': 42, 'name': 'Python 3 (fixture)'}]
    assert all(request.method == 'GET' for request in requests)
    assert 'actual isolation remains unverified' in result['scope']
    assert not settings.runner_verified


def test_probe_does_not_accept_an_unprotected_or_network_enabled_host():
    def handle(request):
        if request.url.path == '/languages':
            return httpx.Response(200, json=[{'id': 1, 'name': 'Python 2'}])
        return httpx.Response(200, json={'enable_network': True, 'allow_enable_network': True})
    settings = PlatformSettings(runner_url='https://runner.example.test', runner_token='fixture-token', runner_language_id=1)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = inspect_runner(settings, client)
    assert not result['configuration_compatible']
    assert not any(result['checks'].values())


def test_probe_rejects_missing_https_or_credentials_without_requesting():
    def handle(request):
        pytest.fail('Invalid configuration must not make a request')
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        for settings in [PlatformSettings(), PlatformSettings(runner_url='http://localhost:2358', runner_token='fixture')]:
            with pytest.raises(ValueError):
                inspect_runner(settings, client)
