"""Coarse job-duration ranges, refined only by compatible completed runs."""
import math
import os
import time
from statistics import median

from sqlalchemy import select
from server.database import Block, Curriculum, Lesson
from server.lessons.contracts import digest


RANGES = {'quick_lesson': (600, 2400), 'curriculum': (180, 900), 'block': (240, 900),
          'prepare_lesson': (300, 1200), 'source': (30, 360), 'grade': (5, 90), 'validate_assessment': (30, 300)}
TARGETS = {'quick_lesson': 'first playable lesson block', 'curriculum': 'curriculum ready for scope review',
           'prepare_lesson': 'requested lesson blocks', 'block': 'lesson block and support',
           'source': 'source preview', 'grade': 'grading result', 'validate_assessment': 'assessment validation'}


def timing_profile():
    return digest({key: os.getenv(key, '') for key in ('PLATFORM_TEXT_PROVIDER', 'PLATFORM_TEXT_MODEL',
        'PLATFORM_VERIFIER_MODEL', 'PLATFORM_SPEECH_PROVIDER', 'PLATFORM_SPEECH_MODEL', 'PIPER_VOICE', 'PLATFORM_RENDERER',
        'PLATFORM_LOCAL_DEMO_PYTHON', 'JUDGE0_PYTHON_LANGUAGE_ID')})


def workload(db, job):
    if job.kind == 'prepare_lesson':
        curriculum = db.get(Curriculum, job.payload.get('curriculum_id'))
        if not curriculum:
            return 1
        ready = set(db.execute(select(Block.objective_id, Block.profile).where(Block.curriculum_id == curriculum.id,
                    Block.context_hash == 'base', Block.state == 'ready')).all())
        from server.learning.adaptation import LEAD
        lesson = db.get(Lesson, curriculum.lesson_id)
        objectives = curriculum.blueprint.get('objectives', [])
        if lesson and not lesson.course_id:
            objectives = objectives[:LEAD]
        return max(1, sum(any((objective['id'], profile) not in ready for profile in ('normal', 'recap'))
                          for objective in objectives))
    return 1


def estimate(job, history, *, units=1, now=None):
    now = time.time() if now is None else now
    timing = job.result.get('_timing', {})
    if job.state == 'running':
        units = timing.get('units', units)
    started = timing.get('started_at')
    elapsed = max(0, now - started) if isinstance(started, (int, float)) and math.isfinite(started) else None
    value = {'status': job.state, 'target': TARGETS.get(job.kind, 'preparation'), 'basis': None,
             'sample_count': 0, 'lower_seconds': None, 'upper_seconds': None,
             'elapsed_seconds': round(elapsed) if elapsed is not None else None, 'queue_wait_included': False}
    if job.state not in {'queued', 'running'} or job.kind not in RANGES:
        return value
    if job.state == 'running' and (job.lease_until is None or job.lease_until <= now):
        return {**value, 'status': 'recovering'}
    profile, samples = timing.get('profile', timing_profile()), []
    for item in history:
        previous = item.result.get('_timing', {})
        duration, previous_units = previous.get('run_seconds'), previous.get('units', 1)
        if (item.kind == job.kind and item.state == 'completed' and previous.get('profile') == profile
                and previous.get('clean_run') is True and isinstance(duration, (int, float))
                and math.isfinite(duration) and duration > 0 and isinstance(previous_units, (int, float)) and previous_units > 0):
            samples.append(duration / previous_units)
    if len(samples) >= 3:
        typical = median(samples) * units
        low, high, basis = max(5, typical * .5), max(15, typical * 1.75), 'recent_completed_runs'
    else:
        low, high = (seconds * units for seconds in RANGES[job.kind])
        basis = 'rough_initial_range'
    value.update(basis=basis, sample_count=len(samples))
    if job.state == 'running':
        if elapsed is None:
            return {**value, 'status': 'timing_unavailable'}
        if elapsed >= high:
            return {**value, 'status': 'taking_longer'}
        low, high = max(0, low - elapsed), high - elapsed
    return {**value, 'lower_seconds': math.ceil(low), 'upper_seconds': math.ceil(high)}
