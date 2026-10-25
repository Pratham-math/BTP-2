"""SQLAlchemy mappings. Production uses migrated PostgreSQL; SQLite is test-only."""
import time
import os
from uuid import uuid4

from sqlalchemy import (JSON, Boolean, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def new_id():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(120), default="Learner")
    privilege: Mapped[str] = mapped_column(String(16), default="student")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Course(Record, Base):
    __tablename__ = "courses"
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    enrollment_hash: Mapped[str | None] = mapped_column(String(64), unique=True)


class Membership(Record, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("course_id", "user_id"),)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Source(Record, Base):
    __tablename__ = "sources"
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"))
    title: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    object_key: Mapped[str | None] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceVersion(Record, Base):
    __tablename__ = "source_versions"
    __table_args__ = (UniqueConstraint("source_id", "number"),)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64))


class Lesson(Record, Base):
    __tablename__ = "lessons"
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    retired: Mapped[bool] = mapped_column(Boolean, default=False)


class Curriculum(Record, Base):
    __tablename__ = "curricula"
    __table_args__ = (UniqueConstraint("lesson_id", "number"),)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    blueprint: Mapped[dict] = mapped_column(JSON)
    availability: Mapped[str] = mapped_column(String(32), default="planning")
    publication: Mapped[str] = mapped_column(String(24), default="draft")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    manifest_revision: Mapped[int] = mapped_column(Integer, default=0)


class Block(Record, Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("curriculum_id", "objective_id", "profile", "context_hash"),)
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"), index=True)
    objective_id: Mapped[str] = mapped_column(String(64))
    profile: Mapped[str] = mapped_column(String(24), default="normal")
    context_hash: Mapped[str] = mapped_column(String(64), default="base")
    state: Mapped[str] = mapped_column(String(24), default="planned")
    script: Mapped[dict] = mapped_column(JSON, default=dict)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str | None] = mapped_column(String(64))


class Asset(Record, Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("block_id", "position", "kind"),)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="clip")
    object_key: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    duration: Mapped[float] = mapped_column(Float)
    mime: Mapped[str] = mapped_column(String(80), default="video/mp4")
    transcript: Mapped[str] = mapped_column(Text, default="")


class Assessment(Record, Base):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("curriculum_id", "objective_id", "variant"),)
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"), index=True)
    objective_id: Mapped[str] = mapped_column(String(64))
    variant: Mapped[str] = mapped_column(String(16), default="base")
    public: Mapped[dict] = mapped_column(JSON)
    private: Mapped[dict] = mapped_column(JSON)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)


class Review(Record, Base):
    __tablename__ = "reviews"
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    approved: Mapped[bool] = mapped_column(Boolean)
    findings: Mapped[dict] = mapped_column(JSON)


class Assignment(Record, Base):
    __tablename__ = "assignments"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"))
    due_at: Mapped[float | None] = mapped_column(Float)


class LearningSession(Record, Base):
    __tablename__ = "learning_sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"))
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("assignments.id"))
    selected_block_id: Mapped[str | None] = mapped_column(ForeignKey("blocks.id"))
    objective_id: Mapped[str] = mapped_column(String(64))
    variant: Mapped[str] = mapped_column(String(16), default="base")
    state: Mapped[str] = mapped_column(String(32), default="preparing")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    route_revision: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    continuation_job_id: Mapped[str | None] = mapped_column(String(36))
    manifest_revision: Mapped[int] = mapped_column(Integer, default=0)
    __mapper_args__ = {"version_id_col": revision}


class Attempt(Record, Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    answer: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(24), default="submitted")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    route_revision: Mapped[int] = mapped_column(Integer)


class Job(Record, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_job_claim", "state", "priority", "created_at"),)
    owner_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(24))
    priority: Mapped[int] = mapped_column(Integer, default=2)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(24), default="queued")
    stage: Mapped[str] = mapped_column(String(60), default="queued")
    lease_until: Mapped[float | None] = mapped_column(Float)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(60))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    consumers: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class StageResult(Record, Base):
    __tablename__ = "stage_results"
    __table_args__ = (UniqueConstraint("job_id", "stage", "input_hash"),)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict] = mapped_column(JSON)


class Issue(Record, Base):
    __tablename__ = "issues"
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"))
    category: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"))
    action: Mapped[str] = mapped_column(String(60))
    target_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


def make_engine(url: str):
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        return engine
    import certifi
    from pathlib import Path
    root = Path(os.getenv("DATABASE_SSL_ROOT_CERT", certifi.where()))
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[1] / root
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_timeout=10, hide_parameters=True,
                         connect_args={"sslmode": "verify-full", "sslrootcert": str(root), "connect_timeout": 10})


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
