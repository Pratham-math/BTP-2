"""User-requested erasure; classroom history keeps an anonymous inactive ID.

Object deletion and Auth calls run outside DB transactions. No cleanup runs
merely because the module is imported or a worker starts.
"""
import os
import shutil
import time
from pathlib import Path
from uuid import UUID
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import delete, func, select

from server.database import (Assessment, Asset, Attempt, AuditEvent, Block, Course,
    Curriculum, Issue, Job, LearningSession, Lesson, Membership, Profile, Source,
    SourceVersion, StageResult)
from server.lessons.contracts import digest
from server.platform_api import Body, DB, User, audit, router
from server.providers.base import GenerationError
from server.config import PROJECT_DIR


class ErasureConfirmation(Body):
    confirmation: str = Field(pattern='^DELETE$')


@router.post('/me/erasure', status_code=202)
def request_erasure(body: ErasureConfirmation, db: DB, user: User):
    # current_user serializes mutations on the profile. Rechecking the last
    # administrator under the common admission lock prevents two simultaneous
    # administrators from removing the only remaining operational owner.
    from server.worker.queue import admission_lock
    admission_lock(db)
    if user.privilege == 'administrator' and db.scalar(select(func.count()).select_from(Profile).where(
            Profile.active.is_(True), Profile.privilege == 'administrator')) <= 1:
        raise HTTPException(409, 'Assign another active administrator before deleting this administrator account.')
    jobs = db.scalars(select(Job).where(Job.owner_id == user.id).order_by(Job.id).with_for_update(nowait=True)).all()
    await_workers = []
    for job in jobs:
        if job.state == 'running':
            await_workers.append({'id': job.id, 'fence': job.fence + 1})
            job.result = {**job.result, 'worker_stopped': False}
        if job.state in {'queued', 'running', 'waiting_for_input', 'waiting_for_review'}:
            job.state, job.fence, job.lease_until = 'cancelled', job.fence + 1, None
    for membership in db.scalars(select(Membership).where(Membership.user_id == user.id)):
        membership.active = False
    for course in db.scalars(select(Course).where(Course.owner_id == user.id)):
        course.enrollment_hash = None
    user.active, user.email, user.display_name, user.privilege = False, '', 'Deleted learner', 'student'
    # Maintenance is not optional model generation and must not be blocked by
    # the generation queue or cloud-call budget.
    job = Job(owner_id=user.id, kind='erase_account', priority=0,
        dedup_key=digest({'kind': 'erase_account', 'user_id': user.id}),
        payload={'user_id': user.id, 'policy': 'anonymize_classroom', 'await_workers': await_workers})
    db.add(job)
    db.flush()
    audit(db, user, 'account_erasure_requested', user.id, policy='anonymize_classroom')
    return {'requested': True, 'job_id': job.id, 'application_access': 'disabled',
        'message': 'Account access is disabled. Private data cleanup is queued. Anonymized classroom records and backups follow the operator retention policy; Auth deletion is tracked separately.'}


@router.get('/admin/erasures')
def erasure_status(db: DB, user: User):
    if user.privilege != 'administrator':
        raise HTTPException(403, 'Administrator privileges are required.')
    return [{'id': job.id, 'account_id': job.owner_id, 'state': job.state,
        'stage': job.stage, 'result': job.result, 'error_code': job.error_code}
        for job in db.scalars(select(Job).where(Job.kind == 'erase_account').order_by(Job.created_at.desc()).limit(100))]


@router.post('/admin/erasures/{job_id}/retry', status_code=202)
def retry_erasure(job_id: str, db: DB, user: User):
    if user.privilege != 'administrator':
        raise HTTPException(403, 'Administrator privileges are required.')
    job = db.scalar(select(Job).where(Job.id == job_id, Job.kind == 'erase_account').with_for_update(nowait=True))
    if not job or job.state not in {'failed', 'waiting_for_input'}:
        raise HTTPException(409, 'Only a failed or blocked erasure can be retried.')
    job.state, job.error_code, job.lease_until, job.updated_at = 'queued', None, None, time.time()
    job.fence += 1
    audit(db, user, 'account_erasure_retried', job.id)
    return {'job_id': job.id, 'state': job.state}


def private_scope(db, user_id):
    lessons = list(db.scalars(select(Lesson).where(Lesson.owner_id == user_id, Lesson.course_id.is_(None))))
    versions = list(db.scalars(select(Curriculum).where(Curriculum.lesson_id.in_([x.id for x in lessons]))))
    blocks = list(db.scalars(select(Block).where(Block.curriculum_id.in_([x.id for x in versions]))))
    assets = list(db.scalars(select(Asset).where(Asset.block_id.in_([x.id for x in blocks]))))
    retained_refs = {ref['source_version_id'] for blueprint in db.scalars(select(Curriculum.blueprint).where(
        Curriculum.id.not_in([x.id for x in versions]))) for obj in blueprint.get('objectives', []) for ref in obj.get('evidence', [])}
    sources = []
    for source in db.scalars(select(Source).where(Source.owner_id == user_id, Source.course_id.is_(None))):
        ids = set(db.scalars(select(SourceVersion.id).where(SourceVersion.source_id == source.id)))
        if not ids.intersection(retained_refs):
            sources.append(source)
    return lessons, versions, blocks, assets, sources


def erasure_inventory(db, user_id):
    _, versions, _, assets, sources = private_scope(db, user_id)
    owned_assets = {x.id for x in assets}
    retained_keys = set(db.scalars(select(Asset.object_key).where(Asset.id.not_in(owned_assets))))
    keys = {x.object_key for x in assets if x.object_key not in retained_keys}
    for source in sources:
        if source.object_key:
            keys.add(source.object_key)
        keys.update(source.metadata_json.get('preview_keys', []))
    private_sources = {x.id for x in sources}
    keep_sources = [x for x in db.scalars(select(Source).where(Source.owner_id == user_id)) if x.id not in private_sources]
    keep_prefixes = [f'sources/{user_id}/{source.id}/' for source in keep_sources]
    keep_exact = {x.object_key for x in keep_sources if x.object_key}
    for source in keep_sources:
        keep_exact.update(source.metadata_json.get('preview_keys', []))
    return {'keys': sorted(keys), 'source_prefix': f'sources/{user_id}/', 'keep_prefixes': keep_prefixes,
        'keep_exact': sorted(keep_exact), 'lesson_prefixes': [f'lessons/{x.id}/' for x in versions],
        'retained_keys': sorted(retained_keys)}


def erasure_keys(inventory, objects):
    # Include uploads left by failed transactions, without holding DB locks
    # during storage I/O. Active owner writes/workers are already fenced/stopped.
    keys = set(inventory['keys'])
    discovered = objects.list_prefix(inventory['source_prefix'])
    keys.update(key for key in discovered if key not in inventory['keep_exact']
        and not any(key.startswith(prefix) for prefix in inventory['keep_prefixes']))
    for prefix in inventory['lesson_prefixes']:
        keys.update(key for key in objects.list_prefix(prefix) if key not in inventory['retained_keys'])
    keys.difference_update(inventory['retained_keys'])
    keys.difference_update(inventory['keep_exact'])
    return sorted(keys)


def scrub_application(db, user_id, job_id):
    lessons, versions, blocks, assets, sources = private_scope(db, user_id)
    for asset in assets:
        db.delete(asset)
    for block in blocks:
        block.script, block.verification, block.checksum, block.state = {}, {}, None, 'erased'
    for assessment in db.scalars(select(Assessment).where(Assessment.curriculum_id.in_([x.id for x in versions]))):
        assessment.public, assessment.private, assessment.validated = {}, {}, False
    for version in versions:
        version.blueprint, version.publication, version.availability = {}, 'retired', 'needs_attention'
    for lesson in lessons:
        lesson.retired, lesson.title = True, 'Deleted private lesson'
    for source in sources:
        source.state, source.title, source.object_key, source.metadata_json = 'retired', 'Deleted private source', None, {}
        for version in db.scalars(select(SourceVersion).where(SourceVersion.source_id == source.id)):
            version.evidence, version.warnings, version.confirmed = [], [], False
    sessions = list(db.scalars(select(LearningSession).where(LearningSession.user_id == user_id)))
    for session in sessions:
        session.position = {}
        if session.assignment_id is None:
            session.state, session.evidence, session.selected_block_id = 'erased', {}, None
        else:
            session.state = 'withdrawn'
            session.evidence = {key: {k: v for k, v in value.items() if k in {'status', 'attempts', 'hints_used', 'viewed', 'first_attempt_passed'}}
                for key, value in session.evidence.items()}
    for attempt in db.scalars(select(Attempt).where(Attempt.user_id == user_id)):
        attempt.answer = {}
        session = next((x for x in sessions if x.id == attempt.session_id), None)
        attempt.result = {k: v for k, v in attempt.result.items() if session and session.assignment_id and k in {'passed', 'objective_status', 'score'}}
        if attempt.state != 'graded':
            attempt.state = 'erased'
    for issue in db.scalars(select(Issue).where(Issue.user_id == user_id)):
        issue.description = '[Removed at account request]'
    old_jobs = list(db.scalars(select(Job).where(Job.owner_id == user_id, Job.id != job_id)))
    db.execute(delete(StageResult).where(StageResult.job_id.in_([x.id for x in old_jobs])))
    for job in old_jobs:
        job.payload, job.result, job.consumers = {}, {}, []
    for event in db.scalars(select(AuditEvent).where(AuditEvent.actor_id == user_id)):
        event.details = {}
    profile = db.get(Profile, user_id)
    profile.active, profile.email, profile.display_name, profile.privilege = False, '', 'Deleted learner', 'student'


def purge_worker_cache(job_id, root=None):
    root = Path(root) if root is not None else PROJECT_DIR / '.run' / 'platform-worker'
    identifier = str(UUID(job_id))
    target = root / identifier
    if root.is_symlink() or target.is_symlink() or target.resolve().parent != root.resolve():
        raise GenerationError('CACHE_ERASURE_FAILED', 'The worker cache path needs operator review; no broad cleanup was attempted.')
    if target.exists():
        shutil.rmtree(target)


def delete_auth_identity(settings, user_id):
    key = os.getenv('SUPABASE_AUTH_ADMIN_KEY', '')
    if not key:
        raise GenerationError('AUTH_ERASURE_NOT_CONFIGURED', 'Application data cleanup completed and access is blocked. Configure the host-only Supabase Auth admin key and retry to remove the authentication identity. Backups and retained classroom records are separate.')
    target = urlsplit(settings.supabase_url)
    if target.scheme != 'https' or not target.hostname or target.username or target.password or target.query or target.fragment:
        raise GenerationError('AUTH_ERASURE_NOT_CONFIGURED', 'Auth administration requires the configured project HTTPS endpoint without embedded credentials.')
    user_id = str(UUID(user_id))
    try:
        response = httpx.delete(settings.supabase_url + '/auth/v1/admin/users/' + user_id,
            headers={'apikey': key, 'Authorization': 'Bearer ' + key}, timeout=20)
        body = response.json() if response.status_code == 404 else {}
        missing = response.status_code == 404 and isinstance(body, dict) and body.get('error_code', body.get('code')) == 'user_not_found'
        if response.status_code not in {200, 204} and not missing:
            raise GenerationError('AUTH_ERASURE_FAILED', 'Supabase did not confirm identity removal. Account access remains blocked; an operator must check Auth and retry.')
    except (httpx.RequestError, ValueError):
        raise GenerationError('AUTH_ERASURE_FAILED', 'The authentication deletion could not be confirmed. Account access remains blocked; retry without recreating the account.') from None


def erase_account(context, settings, objects, runner, payload, folder):
    user_id = payload['user_id']
    inputs = {'user_id': user_id, 'policy': 'anonymize_classroom', 'version': 1}
    with context.transaction() as (db, job):
        profile = db.get(Profile, user_id)
        if job.owner_id != user_id or not profile or profile.active or payload.get('policy') != inputs['policy']:
            raise GenerationError('ERASURE_NOT_REQUESTED', 'Erasure requires an explicitly requested, disabled account with the agreed retention policy.')
    if not context.saved('application_erased', inputs):
        with context.transaction() as (db, _):
            for expected in payload.get('await_workers', []):
                previous = db.get(Job, expected['id'])
                if (not previous or previous.owner_id != user_id or previous.state != 'cancelled'
                        or previous.fence != expected['fence'] or not previous.result.get('worker_stopped')):
                    raise GenerationError('ERASURE_WORKERS_NOT_STOPPED', 'A cancelled worker has not confirmed shutdown. Private cleanup is held rather than racing an upload. An operator must stop the old worker and retry after confirmation.')
        ledger = context.saved('erasure_objects', inputs)
        if ledger is None:
            with context.transaction() as (db, _):
                inventory = erasure_inventory(db, user_id)
            ledger = {'keys': erasure_keys(inventory, objects)}
            context.save('erasure_objects', inputs, ledger)
        for key in ledger['keys']:
            context.check()
            objects.delete(key)  # Idempotent; a partial failure retains the ledger.
        with context.transaction() as (db, job):
            cache_jobs = list(db.scalars(select(Job.id).where(Job.owner_id == user_id, Job.id != job.id)))
        for identifier in cache_jobs:
            context.check()
            purge_worker_cache(identifier)
        with context.transaction() as (db, job):
            scrub_application(db, user_id, job.id)
        context.save('application_erased', inputs, {'completed': True})
        with context.transaction() as (db, job):
            db.execute(delete(StageResult).where(StageResult.job_id == job.id, StageResult.stage == 'erasure_objects'))
    context.check()
    delete_auth_identity(settings, user_id)
    context.check()
    return {'application_data_erased': True, 'auth_identity_erased': True,
        'classroom_records': 'anonymized_and_retained', 'backups': 'expire_under_operator_policy'}
