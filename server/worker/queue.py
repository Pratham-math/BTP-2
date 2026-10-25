import time
import os
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text

from server.database import Job, StageResult
from server.lessons.contracts import digest
from server.providers.base import GenerationError


def admission_lock(db):
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(1875022026)"))


def enqueue(db, settings, owner_id, kind, payload, *, scope, priority=2, consumer=None):
    admission_lock(db)
    identity = {"scope": scope, "kind": kind, "payload": payload, "schema": 1}
    if kind != "grade":
        identity["providers"] = {"author": settings.text_model, "verifier": settings.verifier_model,
            "text_provider": os.getenv("PLATFORM_TEXT_PROVIDER", "gemini"), "speech_provider": os.getenv("PLATFORM_SPEECH_PROVIDER", "gemini"),
            "speech_model": os.getenv("PLATFORM_SPEECH_MODEL", ""), "voice": os.getenv("GEMINI_VOICE", "Kore"),
            "piper_voice": os.getenv("PIPER_VOICE", ""), "template": "platform-author-v2", "renderer": "platform-manim-v2"}
    key = digest(identity)
    previous = db.scalar(select(Job).where(Job.dedup_key == key).with_for_update())
    if previous:
        if consumer and consumer not in previous.consumers:
            previous.consumers = [*previous.consumers, consumer]
        if previous.state == "queued":
            previous.priority = min(priority, previous.priority)
        return previous
    active = ["queued", "running", "waiting_for_input", "waiting_for_review"]
    if db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == owner_id, Job.state.in_(active))) >= settings.max_jobs_per_user:
        raise HTTPException(429, "Your preparation queue is full. Finish or cancel a job first.")
    if db.scalar(select(func.count()).select_from(Job).where(Job.state.in_(["queued", "running"]))) >= settings.max_queue:
        raise HTTPException(429, "The generation queue is full. Try again later.")
    job = Job(owner_id=owner_id, dedup_key=key, kind=kind, payload=payload, priority=priority,
              consumers=[consumer] if consumer else [])
    db.add(job)
    db.flush()
    return job


def requeue(db, settings, job):
    """Retry admission; callers hold admission lock, then a NOWAIT job lock."""
    active = ["queued", "running", "waiting_for_input", "waiting_for_review"]
    if db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == job.owner_id, Job.id != job.id, Job.state.in_(active))) >= settings.max_jobs_per_user:
        raise HTTPException(429, "Your preparation queue is full. Finish or cancel a job before retrying.")
    if db.scalar(select(func.count()).select_from(Job).where(Job.id != job.id, Job.state.in_(["queued", "running"]))) >= settings.max_queue:
        raise HTTPException(429, "The generation queue is full. Retry later.")
    job.state, job.result, job.error_code = "queued", {}, None
    job.fence, job.lease_until, job.updated_at = job.fence + 1, None, time.time()


def claim(factory, *, prefer_oldest=False, lease_seconds=90, queue="all", owner_id=None):
    with factory.begin() as db:
        now = time.time()
        query = select(Job).where(or_(Job.state == "queued", and_(Job.state == "running", Job.lease_until < now)))
        # Allow cancelled render/runner processes to observe their lost fence
        # and terminate before maintenance removes their local private caches.
        query = query.where(or_(Job.kind != 'erase_account', Job.created_at <= now - 120))
        if owner_id is not None:
            query = query.where(Job.owner_id == owner_id)
        if queue == "grading":
            query = query.where(Job.kind == "grade")
        elif queue == "generation":
            query = query.where(Job.kind.not_in(["grade", "erase_account"]))
        elif queue == "maintenance":
            query = query.where(Job.kind == "erase_account")
        elif queue != "all":
            raise ValueError("Unknown worker queue")
        if prefer_oldest:
            query = query.order_by(Job.created_at)
        else:
            # An old bulk job outranks fresh speculation, preventing starvation.
            query = query.order_by((Job.priority != 0), (Job.created_at < now - 300).desc(), Job.priority, Job.created_at)
        job = db.scalar(query.with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        job.state, job.fence, job.lease_until, job.updated_at = "running", job.fence + 1, now + lease_seconds, now
        db.flush()
        return {"id": job.id, "fence": job.fence, "kind": job.kind, "payload": job.payload, "owner_id": job.owner_id}


class JobContext:
    def __init__(self, factory, claim_data):
        self.factory, self.claim = factory, claim_data

    @contextmanager
    def transaction(self):
        with self.factory.begin() as db:
            job = db.scalar(select(Job).where(Job.id == self.claim["id"]).with_for_update())
            if not job or job.state != "running" or job.fence != self.claim["fence"] or job.lease_until < time.time():
                raise GenerationError("LEASE_LOST", "The job was cancelled or another worker recovered it.")
            yield db, job

    def check(self):
        with self.transaction():
            pass

    def heartbeat(self):
        with self.transaction() as (_, job):
            job.lease_until, job.updated_at = time.time() + 90, time.time()

    def saved(self, stage, inputs):
        with self.transaction() as (db, _):
            record = db.scalar(select(StageResult).where(StageResult.job_id == self.claim["id"], StageResult.stage == stage, StageResult.input_hash == digest(inputs)))
            return record.output if record else None

    def save(self, stage, inputs, output):
        with self.transaction() as (db, job):
            key = digest(inputs)
            record = db.scalar(select(StageResult).where(StageResult.job_id == job.id, StageResult.stage == stage, StageResult.input_hash == key))
            if record is None:
                db.add(StageResult(job_id=job.id, stage=stage, input_hash=key, output=output))
            job.stage, job.updated_at = stage, time.time()

    def finish(self, result, state="completed", error_code=None):
        with self.transaction() as (_, job):
            job.state, job.result, job.error_code = state, result, error_code
            job.lease_until, job.updated_at = None, time.time()
