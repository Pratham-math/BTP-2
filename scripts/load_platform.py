"""Opt-in API/media load harness for disposable, authorized classroom accounts.

This is protocol-level load, not a browser/video-quality or security test. Tokens,
answers, signed URLs, response bodies and account IDs never enter the report.
"""
import argparse
import asyncio
import json
import math
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    point = (len(values) - 1) * fraction
    low, high = math.floor(point), math.ceil(point)
    return round(values[low] + (values[high] - values[low]) * (point - low), 2)


class LoadRun:
    def __init__(self, api, media, *, media_hosts=(), interval=5, duration=60, grading_timeout=180):
        self.api, self.media = api, media
        self.media_hosts, self.interval, self.duration = set(media_hosts), interval, duration
        self.grading_timeout, self.samples = grading_timeout, []

    def record(self, operation, actor, start, status=0, size=0, error=None):
        self.samples.append({'operation': operation, 'actor': actor,
            'milliseconds': round((time.monotonic() - start) * 1000, 2),
            'status': status, 'bytes': size, 'error': error})

    async def request(self, method, path, token, actor, operation, body=None):
        start = time.monotonic()
        try:
            response = await self.api.request(method, path, headers={'Authorization': 'Bearer ' + token}, json=body)
            if not response.is_success:
                self.record(operation, actor, start, response.status_code, len(response.content), 'http_failure')
                return None
            result = response.json()
            self.record(operation, actor, start, response.status_code, len(response.content))
            return result
        except (httpx.HTTPError, ValueError):
            self.record(operation, actor, start, error='network_or_invalid_response')
            return None

    async def media_range(self, url, actor, offset=0):
        start = time.monotonic()
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in self.media_hosts or parsed.username or parsed.password:
            self.record('media_range', actor, start, error='unapproved_media_host')
            return False
        try:
            # This separate client has no API Authorization header. Never follow
            # an arbitrary redirect or download an unbounded full video.
            async with self.media.stream('GET', url, headers={'Range': f'bytes={offset}-{offset + 1048575}'}) as response:
                size = 0
                if response.status_code != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    self.record('media_range', actor, start, response.status_code, error='range_not_supported')
                    return False
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1048576:
                        self.record('media_range', actor, start, response.status_code, size, 'range_too_large')
                        return False
                self.record('media_range', actor, start, response.status_code, size)
                return True
        except httpx.HTTPError:
            self.record('media_range', actor, start, error='media_network_failure')
            return False

    async def view(self, session, token, actor):
        deadline, previous = time.monotonic() + self.duration, time.monotonic()
        while time.monotonic() < deadline:
            current = await self.request('GET', f"/api/sessions/{session['id']}", token, actor, 'session_read')
            if current is None:
                return None
            session = current
            now = time.monotonic()
            elapsed, previous = now - previous, now
            if session['state'] == 'playing':
                clip = session['clips'][session['position'].get('clip', 0)]
                access = await self.request('GET', f"/api/assets/{clip['id']}/access?session_id={session['id']}", token, actor, 'media_access')
                if not access or not await self.media_range(access['url'], actor):
                    return None
                offset = min(clip['duration'], session['position'].get('offset', 0) + elapsed)
                session = await self.request('PATCH', f"/api/sessions/{session['id']}/progress", token, actor, 'progress_write', {
                    'expected_revision': session['revision'], 'route_revision': session['route_revision'],
                    'block_id': session['selected_block_id'], 'clip': session['position'].get('clip', 0),
                    'offset': offset, 'ended': offset >= clip['duration']})
                if session is None:
                    return None
            await asyncio.sleep(min(self.interval, max(0, deadline - time.monotonic())))
        return session

    async def submit(self, session, token, actor, answer):
        start = time.monotonic()
        result = await self.request('POST', '/api/attempts', token, actor, 'answer_submit', {
            'session_id': session['id'], 'assessment_id': session['question']['id'],
            'route_revision': session['route_revision'], 'expected_revision': session['revision'],
            'idempotency_key': uuid4().hex, 'answer': answer})
        while result and result['state'] in {'submitted', 'running'} and time.monotonic() - start < self.grading_timeout:
            await asyncio.sleep(1)
            result = await self.request('GET', f"/api/attempts/{result['id']}", token, actor, 'grading_poll')
        self.record('grading_end_to_end', actor, start, status=200 if result and result['state'] == 'graded' else 0,
            error=None if result and result['state'] == 'graded' else 'grading_failed_or_timed_out')

    def report(self, users, mode):
        operations = {}
        for operation in sorted({row['operation'] for row in self.samples}):
            rows = [x for x in self.samples if x['operation'] == operation]
            successful = [x['milliseconds'] for x in rows if not x['error']]
            operations[operation] = {'requests': len(rows), 'failures': sum(bool(x['error']) for x in rows),
                'p50_success_ms': percentile(successful, .5), 'p95_success_ms': percentile(successful, .95),
                'p95_all_ms': percentile([x['milliseconds'] for x in rows], .95),
                'statuses': dict(Counter(str(x['status']) for x in rows)), 'bytes': sum(x['bytes'] for x in rows)}
        return {'kind': 'protocol_load_not_browser_acceptance', 'users': users, 'mode': mode,
            'duration_seconds': self.duration, 'poll_interval_seconds': self.interval,
            'operations': operations, 'samples': self.samples,
            'limitations': ['No browser audiovisual, caption, transition-gap or buffer measurements.',
                'No inference of capacity from mocks or local fixtures.',
                'Provider cost, queue depth, cache coalescing, outage and isolation evidence require separate observation.']}


async def workload(run, tokens, curriculum_id, assignment_id, *, mode, answer=None):
    users = await asyncio.gather(*(run.request('GET', '/api/me', token, i, 'identity_preflight') for i, token in enumerate(tokens)))
    if any(user is None for user in users) or len({user['id'] for user in users}) != len(tokens):
        raise ValueError('All test tokens must identify distinct authorized accounts. No sessions were started.')
    sessions = await asyncio.gather(*(run.request('POST', '/api/sessions', token, i, 'session_start', {
        'curriculum_id': curriculum_id, 'assignment_id': assignment_id}) for i, token in enumerate(tokens)))
    if any(session is None or session.get('curriculum_id') != curriculum_id for session in sessions):
        raise ValueError('Some classroom sessions could not start. Inspect redacted samples before retrying.')
    if mode == 'viewing':
        sessions = await asyncio.gather(*(run.view(session, token, i) for i, (session, token) in enumerate(zip(sessions, tokens))))
    if answer is not None:
        if any(session is None or session.get('state') != 'checkpoint' or not session.get('question') for session in sessions):
            raise ValueError('All test users must reach the shared checkpoint before the synchronized submission burst.')
        if len({session['question']['id'] for session in sessions}) != 1:
            raise ValueError('Test users are at different checkpoints. No submissions were sent.')
        # All preparation has completed before starting the synchronized burst.
        await asyncio.gather(*(run.submit(session, token, i, answer) for i, (session, token) in enumerate(zip(sessions, tokens))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--accounts-file', type=Path, required=True, help='Private JSON list of bearer-token strings, kept in ignored .run/')
    parser.add_argument('--curriculum-id', required=True)
    parser.add_argument('--assignment-id', required=True)
    parser.add_argument('--mode', choices=['viewing', 'submissions'], default='viewing')
    parser.add_argument('--users', type=int, choices=range(1, 201), default=100, metavar='1..200')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--media-host', action='append', default=[])
    parser.add_argument('--answer-file', type=Path, help='Private JSON answer object; required for submissions mode')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--confirm-authorized-test-writes', action='store_true')
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if not args.confirm_authorized_test_writes:
        parser.error('This changes real test progress and can consume service quota. Confirm the authorized disposable test target explicitly.')
    if (parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'} or not parsed.hostname or (parsed.scheme == 'http' and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'})):
        parser.error('Use an HTTPS API origin, or loopback HTTP, with no credentials, path or query.')
    if args.seconds < 1 or args.seconds > 3600 or args.output.exists():
        parser.error('Use 1..3600 seconds and a new output path; existing reports are never overwritten.')
    tokens = json.loads(args.accounts_file.read_text(encoding='utf-8'))
    if (not isinstance(tokens, list) or len(tokens) < args.users or any(not isinstance(x, str) or not x.strip() for x in tokens)):
        parser.error('The accounts file must contain enough nonempty token strings.')
    tokens = tokens[:args.users]
    if len(set(tokens)) != len(tokens):
        parser.error('Use distinct accounts, not repeated tokens.')
    answer = json.loads(args.answer_file.read_text(encoding='utf-8')) if args.answer_file else None
    if args.mode == 'submissions' and not isinstance(answer, dict):
        parser.error('Submissions mode requires a private JSON answer object.')

    async def execute():
        limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
        async with httpx.AsyncClient(base_url=args.base_url, timeout=30, limits=limits, follow_redirects=False) as api, httpx.AsyncClient(timeout=30, limits=limits, follow_redirects=False) as media:
            run = LoadRun(api, media, media_hosts=args.media_host, duration=args.seconds)
            failure = None
            try:
                await workload(run, tokens, args.curriculum_id, args.assignment_id, mode=args.mode, answer=answer)
            except (ValueError, KeyError, TypeError, IndexError):
                failure = 'Workload incomplete. Check account uniqueness, session/checkpoint readiness and redacted HTTP samples.'
            report = run.report(len(tokens), args.mode)
            report['completed'] = failure is None
            report['failure'] = failure
            with args.output.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
            print(json.dumps({'completed': report['completed'], 'operations': report['operations'], 'failure': failure}))
            return 0 if failure is None and not any(x['error'] for x in run.samples) else 1
    raise SystemExit(asyncio.run(execute()))


if __name__ == '__main__':
    main()
