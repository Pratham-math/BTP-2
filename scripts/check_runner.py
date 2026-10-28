"""Read-only Judge0 configuration probe. Never submits code or changes settings."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from server.platform_settings import PlatformSettings


def inspect_runner(settings, client):
    try:
        url = urlsplit(settings.runner_url)
        valid = url.scheme == 'https' and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
    except ValueError:
        valid = False
    if not valid or not settings.runner_token:
        raise ValueError('Set an HTTPS JUDGE0_URL and a server-only JUDGE0_TOKEN in .env first.')

    def read(path):
        response = client.get(settings.runner_url.rstrip('/') + path)
        response.raise_for_status()
        return response.json()

    languages, config = read('/languages'), read('/config_info')
    if not isinstance(languages, list) or not isinstance(config, dict):
        raise ValueError('The server did not return the expected Judge0 API format.')
    python = [{'id': item['id'], 'name': item['name']} for item in languages
              if isinstance(item, dict) and isinstance(item.get('id'), int)
              and isinstance(item.get('name'), str) and 'python' in item['name'].lower()]
    selected = any(item['id'] == settings.runner_language_id and 'python 3' in item['name'].lower() for item in python)
    anonymous = client.get(settings.runner_url.rstrip('/') + '/languages', headers={'X-Auth-Token': ''})
    limits = {'max_cpu_time_limit': 2, 'max_wall_time_limit': 5, 'max_memory_limit': 131072,
              'max_stack_limit': 8192, 'max_max_processes_and_or_threads': 1, 'max_max_file_size': 64}
    compatible_limits = all(isinstance(config.get(key), (int, float)) and config[key] >= value for key, value in limits.items())
    checks = {'selected_python3_language': selected, 'anonymous_requests_rejected': anonymous.status_code in {401, 403},
              'network_disabled_by_default': config.get('enable_network') is False,
              'submissions_cannot_enable_network': config.get('allow_enable_network') is False,
              'requested_limits_accepted_by_configuration': compatible_limits}
    return {'checks': checks, 'python_languages': python,
            'configuration_compatible': all(checks.values()),
            'scope': 'Read-only configuration only. No code executed; actual isolation remains unverified.'}


def main():
    settings = PlatformSettings.from_env()
    try:
        with httpx.Client(timeout=15, follow_redirects=False, headers={'X-Auth-Token': settings.runner_token}) as client:
            result = inspect_runner(settings, client)
        print(json.dumps(result, indent=2))
        return 0 if result['configuration_compatible'] else 1
    except httpx.HTTPStatusError as error:
        print(f'Runner rejected a configuration request (HTTP {error.response.status_code}). Check the URL, token and proxy permissions.', file=sys.stderr)
    except httpx.RequestError:
        print('Cannot reach the runner securely. Check DNS, HTTPS certificate, firewall and connectivity.', file=sys.stderr)
    except (ValueError, TypeError, KeyError):
        print('Runner configuration is missing or invalid. Check JUDGE0_URL, JUDGE0_TOKEN and the Judge0 API response format; see PYTHON_RUNNER_SETUP.md.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
