import asyncio
import json

import httpx
import pytest

from scripts.load_platform import LoadRun, percentile, workload


def test_load_harness_burst_uses_distinct_accounts_and_redacts_credentials_and_answers():
    writes = []
    def respond(request):
        token = request.headers.get('Authorization', '')
        if request.url.path == '/api/me':
            return httpx.Response(200, json={'id': token})
        if request.url.path == '/api/sessions':
            return httpx.Response(201, json={'id': 'session-' + token[-1], 'curriculum_id': 'fixture-version',
                'state': 'checkpoint', 'revision': 2, 'route_revision': 1, 'question': {'id': 'fixture-question'}})
        if request.url.path == '/api/attempts':
            writes.append(json.loads(request.content))
            return httpx.Response(202, json={'id': 'fixture-attempt', 'state': 'graded'})
        raise AssertionError('Unexpected fixture request')
    async def execute():
        async with httpx.AsyncClient(base_url='https://api.fixture.test', transport=httpx.MockTransport(respond)) as api, httpx.AsyncClient() as media:
            run = LoadRun(api, media, duration=1)
            await workload(run, ['fixture-private-token-a', 'fixture-private-token-b'], 'fixture-version', 'fixture-assignment',
                mode='submissions', answer={'code': 'private fixture solution'})
            return run.report(2, 'submissions')
    report = asyncio.run(execute())
    assert len(writes) == 2 and len({row['idempotency_key'] for row in writes}) == 2
    assert report['operations']['grading_end_to_end']['failures'] == 0
    assert 'fixture-private-token' not in json.dumps(report) and 'private fixture solution' not in json.dumps(report)


def test_duplicate_identities_are_rejected_before_any_test_writes():
    methods = []
    def respond(request):
        methods.append(request.method)
        return httpx.Response(200, json={'id': 'same-fixture-account'})
    async def execute():
        async with httpx.AsyncClient(base_url='https://api.fixture.test', transport=httpx.MockTransport(respond)) as api, httpx.AsyncClient() as media:
            with pytest.raises(ValueError, match='distinct'):
                await workload(LoadRun(api, media), ['first-fixture-token', 'second-fixture-token'], 'v', 'a', mode='submissions', answer={})
    asyncio.run(execute())
    assert methods == ['GET', 'GET']


def test_media_range_never_forwards_api_credentials_or_follows_unapproved_hosts():
    requests = []
    def respond(request):
        requests.append(request)
        assert 'Authorization' not in request.headers
        return httpx.Response(206, headers={'Content-Range': 'bytes 0-3/4'}, content=b'DATA')
    async def execute():
        async with httpx.AsyncClient() as api, httpx.AsyncClient(transport=httpx.MockTransport(respond)) as media:
            run = LoadRun(api, media, media_hosts=['media.fixture.test'])
            assert not await run.media_range('https://unapproved.fixture.test/private?token=secret-fixture', 0)
            assert await run.media_range('https://media.fixture.test/fixture?signature=secret-fixture', 0)
            report = run.report(1, 'viewing')
            assert 'secret-fixture' not in json.dumps(report)
            assert report['operations']['media_range']['failures'] == 1
    asyncio.run(execute())
    assert len(requests) == 1


def test_percentiles_include_a_separate_all_request_distribution():
    assert percentile([1, 2, 3, 4], .95) == 3.85
    assert percentile([], .5) is None
