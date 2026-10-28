"""Authenticated resource APIs. Expensive preparation runs only in the worker."""
import hashlib
import secrets
import tempfile
import time
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from server.auth import current_user, curriculum_access, enrolled, get_db, lesson_access, own_course
from server.database import (Assessment, Asset, Assignment, AuditEvent, Block, Course,
    Attempt, Curriculum, Issue, Job, LearningSession, Lesson, Membership, Profile, Review, Source, SourceVersion, new_id)
from server.ingestion.readers import text_blocks, youtube_id
from server.lessons.contracts import EvidenceBlock, digest
from server.worker.queue import admission_lock, enqueue, requeue
from server.worker.estimates import estimate, workload


router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db, scope="function")]
User = Annotated[Profile, Depends(current_user, scope="function")]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class CourseInput(Body):
    title: str = Field(min_length=3, max_length=160)


class JoinInput(Body):
    code: str = Field(min_length=12, max_length=80)


class SourceInput(Body):
    title: str = Field(min_length=3, max_length=160)
    kind: Literal["text", "topic", "youtube"]
    text: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=3, max_length=250000)
    course_id: str | None = None


class Correction(Body):
    expected_version: int = Field(ge=1)
    evidence: list[EvidenceBlock] = Field(min_length=1)
    confirm: bool
    note: str = Field(min_length=5, max_length=1000)


class SourceTitle(Body):
    title: str = Field(min_length=3, max_length=160)


class LessonInput(Body):
    title: str = Field(min_length=3, max_length=160)
    goal: str = Field(min_length=10, max_length=6000)
    source_ids: list[str] = Field(min_length=1, max_length=20)
    course_id: str | None = None


class VersionConfirmation(Body):
    expected_fingerprint: str = Field(min_length=64, max_length=64)


class ReviewInput(VersionConfirmation):
    coverage: bool
    factual: bool
    assessments: bool
    media: bool
    findings: str = Field(default="", max_length=5000)


class AssignmentInput(Body):
    curriculum_id: str
    due_at: float | None = None


class IssueInput(Body):
    curriculum_id: str
    category: Literal["content", "assessment", "accessibility", "playback"]
    description: str = Field(min_length=10, max_length=5000)


def audit(db, user, action, target, **details):
    db.add(AuditEvent(actor_id=user.id, action=action, target_id=target, details=details))


def source_access(db, user, source_id):
    source = db.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if not source or source.owner_id != user.id or source.state == "retired":
        raise HTTPException(404, "Source not found.")
    return source


def source_view(db, source):
    version = db.scalar(select(SourceVersion).where(SourceVersion.source_id == source.id, SourceVersion.number == source.current_version))
    return {"id": source.id, "title": source.title, "kind": source.kind, "state": source.state,
            "has_original": bool(source.object_key),
            "original_url": "https://www.youtube.com/watch?v=" + youtube_id(source.metadata_json["input"]) if source.kind == "youtube" else None,
            "job_id": source.metadata_json.get("job_id"),
            "course_id": source.course_id, "version": source.current_version,
            "source_version_id": version.id if version else None, "evidence": version.evidence if version else [],
            "warnings": version.warnings if version else [], "confirmed": version.confirmed if version else False}


def fingerprint(db, curriculum):
    blocks = db.scalars(select(Block).where(Block.curriculum_id == curriculum.id).order_by(Block.id)).all()
    assets = db.scalars(select(Asset).join(Block, Asset.block_id == Block.id).where(Block.curriculum_id == curriculum.id).order_by(Asset.id)).all()
    questions = db.scalars(select(Assessment).where(Assessment.curriculum_id == curriculum.id).order_by(Assessment.id)).all()
    return digest({"curriculum": curriculum.blueprint,
        "blocks": [{"id": x.id, "script": x.script, "verification": x.verification, "state": x.state, "checksum": x.checksum} for x in blocks],
        "assets": [{"id": x.id, "key": x.object_key, "checksum": x.checksum, "duration": x.duration} for x in assets],
        "questions": [{"id": x.id, "public": x.public, "private": x.private, "validated": x.validated} for x in questions]})


def curriculum_view(db, curriculum):
    lesson = db.get(Lesson, curriculum.lesson_id)
    blocks = db.scalars(select(Block).where(Block.curriculum_id == curriculum.id)).all()
    return {"id": curriculum.id, "lesson_id": lesson.id, "title": lesson.title, "number": curriculum.number,
            "course_id": lesson.course_id, "blueprint": curriculum.blueprint,
            "availability": curriculum.availability, "publication": curriculum.publication,
            "confirmed": curriculum.confirmed, "manifest_revision": curriculum.manifest_revision,
            "fingerprint": fingerprint(db, curriculum),
            "blocks": [{"id": x.id, "objective_id": x.objective_id, "profile": x.profile, "state": x.state} for x in blocks]}


@router.get("/me")
def me(user: User):
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "privilege": user.privilege}


@router.post("/admin/users/{user_id}/privilege")
def grant_privilege(user_id: str, value: Literal["student", "teacher", "administrator"], db: DB, user: User):
    if user.privilege != "administrator":
        raise HTTPException(403, "Administrator privileges are required.")
    target = db.get(Profile, user_id)
    if not target:
        raise HTTPException(404, "The user must sign in before privileges can be granted.")
    if target.id == user.id and value != "administrator":
        raise HTTPException(409, "Use another administrator to change your own role.")
    target.privilege = value
    audit(db, user, "privilege_changed", target.id, privilege=value)
    return {"id": target.id, "privilege": target.privilege}


@router.get("/courses")
def courses(db: DB, user: User):
    member_courses = select(Membership.course_id).where(Membership.user_id == user.id, Membership.active.is_(True))
    return [{"id": x.id, "title": x.title, "role": "teacher" if x.owner_id == user.id else "student"}
            for x in db.scalars(select(Course).where(or_(Course.owner_id == user.id, Course.id.in_(member_courses))))]


@router.post("/courses", status_code=201)
def create_course(body: CourseInput, db: DB, user: User):
    if user.privilege not in {"teacher", "administrator"}:
        raise HTTPException(403, "A verified teacher must create this course.")
    code = secrets.token_urlsafe(12)
    course = Course(owner_id=user.id, title=body.title, enrollment_code=code,
                    enrollment_hash=hashlib.sha256(code.encode()).hexdigest(), enrollment_enabled=True)
    db.add(course)
    db.flush()
    audit(db, user, "course_created", course.id)
    return {"id": course.id, "title": course.title, "role": "teacher"}


def teacher_course(db, user, course_id):
    course = db.scalar(select(Course).where(Course.id == course_id, Course.owner_id == user.id).with_for_update())
    if not course:
        raise HTTPException(404, 'Course not found.')
    return course


def permanent_code(course):
    if not course.enrollment_code:
        course.enrollment_code = secrets.token_urlsafe(12)
        # Preserve the last legacy hash-only invitation instead of invalidating it.
        if not course.enrollment_hash:
            course.enrollment_hash = hashlib.sha256(course.enrollment_code.encode()).hexdigest()
    return {'code': course.enrollment_code, 'enabled': course.enrollment_enabled}


@router.get('/courses/{course_id}/enrollment-code')
def get_enrollment_code(course_id: str, db: DB, user: User):
    return permanent_code(teacher_course(db, user, course_id))


@router.post('/courses/{course_id}/enrollment-code')
def enable_enrollment(course_id: str, db: DB, user: User):
    course = teacher_course(db, user, course_id)
    course.enrollment_enabled = True
    audit(db, user, 'enrollment_enabled', course.id)
    return permanent_code(course)


@router.delete("/courses/{course_id}/enrollment-code")
def revoke_code(course_id: str, db: DB, user: User):
    course = teacher_course(db, user, course_id)
    course.enrollment_enabled = False
    audit(db, user, "enrollment_disabled", course.id)
    return {"revoked": True}


@router.post("/courses/join")
def join_course(body: JoinInput, db: DB, user: User):
    # Serialize admission so duplicate tabs cannot create duplicate membership.
    from server.worker.queue import admission_lock
    admission_lock(db)
    course = db.scalar(select(Course).where(Course.enrollment_enabled.is_(True),
        or_(Course.enrollment_hash == hashlib.sha256(body.code.encode()).hexdigest(), Course.enrollment_code == body.code)).with_for_update())
    if not course:
        raise HTTPException(404, "This enrollment code is invalid or enrollment is paused.")
    if course.owner_id == user.id:
        return {'id': course.id, 'title': course.title}
    membership = db.scalar(select(Membership).where(Membership.course_id == course.id, Membership.user_id == user.id).with_for_update())
    if membership and not membership.active:
        if not membership.left_voluntarily:
            raise HTTPException(403, "A teacher must restore your revoked membership.")
        membership.active, membership.left_voluntarily = True, False
    if membership is None:
        db.add(Membership(course_id=course.id, user_id=user.id))
    return {"id": course.id, "title": course.title}


@router.post('/courses/{course_id}/leave')
def leave_course(course_id: str, db: DB, user: User):
    course = db.get(Course, course_id)
    if course and course.owner_id == user.id:
        raise HTTPException(409, 'The teacher cannot leave their own classroom.')
    membership = db.scalar(select(Membership).where(Membership.course_id == course_id,
        Membership.user_id == user.id, Membership.active.is_(True)).with_for_update())
    if not membership:
        raise HTTPException(404, 'Active classroom membership not found.')
    membership.active, membership.left_voluntarily = False, True
    audit(db, user, 'classroom_left', course_id)
    return {'left': True, 'retained': 'Assignment history is retained. You may rejoin with the permanent class code.'}


@router.get("/courses/{course_id}/members")
def members(course_id: str, db: DB, user: User):
    own_course(db, user, course_id)
    return [{"id": x.id, "display_name": profile.display_name, "active": x.active, 'left_voluntarily': x.left_voluntarily}
            for x, profile in db.execute(select(Membership, Profile).join(Profile, Profile.id == Membership.user_id).where(Membership.course_id == course_id))]


@router.patch("/courses/{course_id}/members/{membership_id}")
def set_membership(course_id: str, membership_id: str, active: bool, db: DB, user: User):
    own_course(db, user, course_id)
    membership = db.scalar(select(Membership).where(Membership.id == membership_id, Membership.course_id == course_id).with_for_update())
    if not membership or membership.course_id != course_id:
        raise HTTPException(404, "Membership not found.")
    if active and membership.left_voluntarily:
        raise HTTPException(409, 'This learner chose to leave. They can rejoin with the class code.')
    membership.active, membership.left_voluntarily = active, False
    audit(db, user, "membership_changed", membership.id, active=active)
    return {"id": membership.id, "active": active}


@router.get("/sources")
def sources(db: DB, user: User):
    rows = db.execute(select(Source, SourceVersion).outerjoin(SourceVersion,
        (SourceVersion.source_id == Source.id) & (SourceVersion.number == Source.current_version))
        .where(Source.owner_id == user.id, Source.state != "retired").order_by(Source.created_at.desc())).all()
    job_ids = [source.metadata_json.get("job_id") for source, _ in rows if source.metadata_json.get("job_id")]
    jobs = {job.id: job for job in db.scalars(select(Job).where(Job.id.in_(job_ids), Job.owner_id == user.id))} if job_ids else {}
    return [{"id": source.id, "title": source.title, "kind": source.kind, "state": source.state,
             "created_at": source.created_at, "version": source.current_version,
             "block_count": len(version.evidence) if version else 0,
             "unresolved_blocks": sum(bool(block.get("uncertainty")) for block in version.evidence) if version else 0,
             "job_state": jobs[source.metadata_json["job_id"]].state if source.metadata_json.get("job_id") in jobs else None}
            for source, version in rows]


@router.post("/sources", status_code=201)
def create_source(body: SourceInput, request: Request, db: DB, user: User):
    if not request.app.state.settings.source_features().get(body.kind):
        raise HTTPException(503, "This source adapter is not enabled for verified use. Add corrected text notes or finish the adapter's setup and acceptance checks.")
    if body.course_id:
        own_course(db, user, body.course_id)
    source = Source(owner_id=user.id, course_id=body.course_id, title=body.title, kind=body.kind,
                    metadata_json={"input": body.text})
    db.add(source)
    db.flush()
    if body.kind == "text":
        evidence = text_blocks(body.text)
        db.add(SourceVersion(source_id=source.id, number=1, evidence=evidence, warnings=[], content_hash=digest(evidence)))
        source.current_version, source.state = 1, "needs_confirmation"
    else:
        if body.kind == "youtube":
            source.metadata_json = {"input": "https://www.youtube.com/watch?v=" + youtube_id(body.text)}
        job = enqueue(db, request.app.state.settings, user.id, "source", {"source_id": source.id}, scope=f"private:{user.id}")
        source.metadata_json = {**source.metadata_json, "job_id": job.id}
    db.flush()
    return source_view(db, source)


@router.post("/sources/upload", status_code=202)
def upload_source(request: Request, db: DB, user: User, file: UploadFile = File(...)):
    name = Path(file.filename or "source").name
    suffix = Path(name).suffix.lower()
    kinds = {".pdf": "pdf", ".pptx": "pptx", ".ppt": "ppt", ".png": "image", ".jpg": "image", ".jpeg": "image"}
    if suffix not in kinds:
        raise HTTPException(422, "Upload PDF, PPTX, PPT, PNG or JPEG source material.")
    feature = "image" if kinds[suffix] == "image" else "document"
    if not request.app.state.settings.source_features()[feature]:
        raise HTTPException(503, "This upload adapter is not enabled until storage, isolation and extraction checks pass. Corrected text notes are available.")
    size, settings = 0, request.app.state.settings
    with tempfile.TemporaryDirectory(prefix="btp-upload-") as folder:
        path = Path(folder) / ("source" + suffix)
        with path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "This source exceeds the 25 MB upload limit. Split it into explicit batches.")
                output.write(chunk)
        if size == 0:
            raise HTTPException(422, "The source is empty.")
        source = Source(id=new_id(), owner_id=user.id, title=name[:160], kind=kinds[suffix], metadata_json={"suffix": suffix, "size": size})
        source.object_key = f"sources/{user.id}/{source.id}/original{suffix}"
        request.app.state.objects.put(source.object_key, path, file.content_type or "application/octet-stream")
    db.add(source)
    db.flush()
    job = enqueue(db, settings, user.id, "source", {"source_id": source.id}, scope=f"private:{user.id}")
    source.metadata_json = {**source.metadata_json, "job_id": job.id}
    return {"id": source.id, "state": "pending", "job_id": job.id}


@router.get("/sources/{source_id}")
def get_source(source_id: str, db: DB, user: User):
    return source_view(db, source_access(db, user, source_id))


@router.patch("/sources/{source_id}")
def rename_source(source_id: str, body: SourceTitle, db: DB, user: User):
    source = source_access(db, user, source_id)
    source.title = body.title
    audit(db, user, "source_renamed", source.id)
    return source_view(db, source)


@router.get("/sources/{source_id}/original")
def original_source(source_id: str, request: Request, db: DB, user: User):
    source = source_access(db, user, source_id)
    if not source.object_key:
        raise HTTPException(404, "This source has no uploaded original.")
    return {"url": request.app.state.objects.sign(source.object_key), "expires_at": time.time() + 300}


@router.put("/sources/{source_id}/preview")
def correct_source(source_id: str, body: Correction, db: DB, user: User):
    source = source_access(db, user, source_id)
    if source.current_version != body.expected_version:
        raise HTTPException(409, "This source changed in another tab. Reload before saving.")
    if len({x.id for x in body.evidence}) != len(body.evidence):
        raise HTTPException(422, "Evidence block IDs must be unique.")
    if body.confirm and any(x.uncertainty for x in body.evidence):
        raise HTTPException(409, "Correct every uncertain block and clear its warnings before confirming.")
    evidence = [x.model_dump() for x in body.evidence]
    allowed_images = {source.object_key, *source.metadata_json.get('preview_keys', [])}
    if any(x["image_key"] and x["image_key"] not in allowed_images for x in evidence):
        raise HTTPException(422, "Evidence images must belong to this uploaded source.")
    source.current_version += 1
    source.state = "confirmed" if body.confirm else "needs_confirmation"
    db.add(SourceVersion(source_id=source.id, number=source.current_version, evidence=evidence,
                          confirmed=body.confirm, warnings=[], content_hash=digest(evidence)))
    audit(db, user, "source_corrected", source.id, version=source.current_version, note=body.note)
    db.flush()
    return source_view(db, source)


@router.get('/sources/{source_id}/evidence/{block_id}/image')
def evidence_image(source_id: str, block_id: str, request: Request, db: DB, user: User):
    source = source_access(db, user, source_id)
    version = source_view(db, source)
    block = next((x for x in version['evidence'] if x['id'] == block_id), None)
    allowed = {source.object_key, *source.metadata_json.get('preview_keys', [])}
    if not block or not block.get('image_key') or block['image_key'] not in allowed:
        raise HTTPException(404, 'Source image not found.')
    return {'url': request.app.state.objects.sign(block['image_key']), 'expires_at': time.time() + 300}


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, request: Request, db: DB, user: User):
    source = source_access(db, user, source_id)
    versions = set(db.scalars(select(SourceVersion.id).where(SourceVersion.source_id == source.id)))
    for job in db.scalars(select(Job).where(Job.owner_id == user.id, Job.state.in_(["queued", "running", "waiting_for_input", "waiting_for_review"]))):
        if source.id in job.payload.get("source_ids", []) or versions.intersection(job.payload.get("source_version_ids", [])):
            raise HTTPException(409, "Cancel the lesson preparation using this source before removing it.")
    for curriculum in db.scalars(select(Curriculum).join(Lesson, Lesson.id == Curriculum.lesson_id).where(Lesson.retired.is_(False))):
        if any(ref["source_version_id"] in versions for objective in curriculum.blueprint.get("objectives", []) for ref in objective["evidence"]):
            raise HTTPException(409, "Retire lessons using this source before deleting its original. Saved classroom records follow the retention policy.")
    if source.object_key:
        request.app.state.objects.delete(source.object_key)
    for key in source.metadata_json.get('preview_keys', []):
        if key != source.object_key:
            request.app.state.objects.delete(key)
    source.state, source.metadata_json = "retired", {}
    for version in db.scalars(select(SourceVersion).where(SourceVersion.source_id == source.id)):
        version.evidence, version.warnings = [], []
    audit(db, user, "source_deleted", source.id)
    return {"deleted": True, "retained": "An ID and deletion audit remain; backups expire under the configured retention policy."}


@router.get("/lessons")
def lessons(db: DB, user: User):
    owned_courses = select(Course.id).where(Course.owner_id == user.id)
    rows = db.scalars(select(Lesson).where(or_(Lesson.owner_id == user.id, Lesson.course_id.in_(owned_courses)), Lesson.retired.is_(False)).order_by(Lesson.created_at.desc()))
    result = []
    for lesson in rows:
        version = db.scalar(select(Curriculum).where(Curriculum.lesson_id == lesson.id).order_by(Curriculum.number.desc()).limit(1))
        result.append({"id": lesson.id, "title": lesson.title, "course_id": lesson.course_id,
                       "curriculum_id": version.id if version else None, "availability": version.availability if version else "planning",
                       "publication": version.publication if version else "draft"})
    return result


@router.post("/lessons", status_code=202)
def create_lesson(body: LessonInput, request: Request, db: DB, user: User):
    if body.course_id:
        own_course(db, user, body.course_id)
    versions = []
    for source_id in dict.fromkeys(body.source_ids):
        source = source_access(db, user, source_id)
        version = db.scalar(select(SourceVersion).where(SourceVersion.source_id == source.id, SourceVersion.number == source.current_version))
        if source.state != "confirmed" or not version or not version.confirmed:
            raise HTTPException(409, "Confirm every source preview before planning the lesson.")
        versions.append(version.id)
    lesson = Lesson(owner_id=user.id, course_id=body.course_id, title=body.title)
    db.add(lesson)
    db.flush()
    settings = request.app.state.settings
    job = enqueue(db, settings, user.id, "curriculum", {"lesson_id": lesson.id, "source_version_ids": versions,
        "goal": body.goal, "text_model": settings.text_model, "verifier_model": settings.verifier_model}, scope=f"private:{user.id}")
    return {"id": lesson.id, "job_id": job.id, "state": "planning"}


UPLOAD_KINDS = {".pdf": "pdf", ".pptx": "pptx", ".png": "image", ".jpg": "image", ".jpeg": "image"}


@router.post("/lessons/quick", status_code=202)
def quick_lesson(request: Request, db: DB, user: User, prompt: str = Form(..., min_length=10, max_length=6000),
                 title: str = Form("", max_length=160), notes: str = Form("", max_length=250000),
                 reference: bool = Form(False), files: list[UploadFile] = File(default=[])):
    """Prompt + any mix of notes, documents and a reference article -> one preparation job."""
    settings, features = request.app.state.settings, request.app.state.settings.source_features()
    if len(files) > 5:
        raise HTTPException(422, "Attach up to 5 files per lesson.")
    title = title.strip() or prompt.strip().splitlines()[0][:80]
    if len(title) < 3:
        raise HTTPException(422, "Give the lesson a title of at least 3 characters.")
    sources = []
    if notes.strip():
        source = Source(owner_id=user.id, title=f"Notes: {title}"[:160], kind="text", metadata_json={"input": notes})
        db.add(source)
        db.flush()
        evidence = text_blocks(notes)
        db.add(SourceVersion(source_id=source.id, number=1, evidence=evidence, warnings=[], content_hash=digest(evidence)))
        source.current_version, source.state = 1, "needs_confirmation"
        sources.append(source)
    for upload in files:
        name = Path(upload.filename or "source").name
        suffix = Path(name).suffix.lower()
        kind = UPLOAD_KINDS.get(suffix)
        if not kind or not features["image" if kind == "image" else "document"]:
            raise HTTPException(422, f"{name}: attach PDF or PPTX files" + (", PNG or JPEG images." if features["image"] else "."))
        size, source = 0, Source(id=new_id(), owner_id=user.id, title=name[:160], kind=kind, metadata_json={"suffix": suffix})
        with tempfile.TemporaryDirectory(prefix="btp-upload-") as folder:
            path = Path(folder) / ("source" + suffix)
            with path.open("wb") as output:
                while chunk := upload.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, f"{name} exceeds the 25 MB upload limit. Split it into smaller files.")
                    output.write(chunk)
            if size == 0:
                raise HTTPException(422, f"{name} is empty.")
            source.object_key = f"sources/{user.id}/{source.id}/original{suffix}"
            source.metadata_json = {**source.metadata_json, "size": size}
            request.app.state.objects.put(source.object_key, path, upload.content_type or "application/octet-stream")
        db.add(source)
        sources.append(source)
    if reference or not sources:
        source = Source(owner_id=user.id, title=f"Reference: {title}"[:160], kind="topic", metadata_json={"input": title})  # The short title searches better than a long prompt.
        db.add(source)
        sources.append(source)
    db.flush()
    lesson = Lesson(owner_id=user.id, title=title)
    db.add(lesson)
    db.flush()
    job = enqueue(db, settings, user.id, "quick_lesson", {"lesson_id": lesson.id, "source_ids": [x.id for x in sources], "goal": prompt},
                  scope=f"private:{user.id}")
    for source in sources:
        source.metadata_json = {**source.metadata_json, "job_id": job.id}
    return {"id": lesson.id, "job_id": job.id, "state": "preparing"}


@router.get("/lessons/versions/{curriculum_id}")
def get_curriculum(curriculum_id: str, db: DB, user: User):
    curriculum = curriculum_access(db, user, curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    course = db.get(Course, lesson.course_id) if lesson.course_id else None
    return {**curriculum_view(db, curriculum), 'can_manage': lesson.owner_id == user.id or bool(course and course.owner_id == user.id)}


@router.post("/lessons/versions/{curriculum_id}/confirm", status_code=202)
def confirm_curriculum(curriculum_id: str, body: VersionConfirmation, request: Request, db: DB, user: User):
    curriculum = curriculum_access(db, user, curriculum_id, edit=True)
    if curriculum.publication != "draft":
        raise HTTPException(409, "Approved versions are immutable. Create a new draft version.")
    if fingerprint(db, curriculum) != body.expected_fingerprint:
        raise HTTPException(409, "This curriculum changed. Reload its scope before confirming.")
    curriculum.confirmed, curriculum.availability = True, "preparing_first_block"
    first = curriculum.blueprint["objectives"][0]["id"]
    lesson = db.get(Lesson, curriculum.lesson_id)
    job = enqueue(db, request.app.state.settings, lesson.owner_id, "block",
        {"curriculum_id": curriculum.id, "objective_id": first, "profile": "normal", "context_hash": "base", "misconception": None},
        scope=f"private:{lesson.owner_id}:{curriculum.id}")
    from server.learning.service import enqueue_initial_window
    enqueue_initial_window(db, request.app.state.settings, curriculum, lesson)
    audit(db, user, "curriculum_confirmed", curriculum.id)
    return {"job_id": job.id, "curriculum_id": curriculum.id}


@router.post("/lessons/versions/{curriculum_id}/prepare", status_code=202)
def prepare_remaining(curriculum_id: str, request: Request, db: DB, user: User):
    curriculum = curriculum_access(db, user, curriculum_id, edit=True)
    if not curriculum.confirmed or curriculum.publication != "draft":
        raise HTTPException(409, "Only a confirmed draft can be prepared.")
    lesson = db.get(Lesson, curriculum.lesson_id)
    job = enqueue(db, request.app.state.settings, lesson.owner_id, "prepare_lesson", {"curriculum_id": curriculum.id}, scope=f"private:{lesson.owner_id}:{curriculum.id}")
    return {"job_id": job.id}


@router.delete('/lessons/{lesson_id}')
@router.post("/lessons/{lesson_id}/retire")
def retire_lesson(lesson_id: str, db: DB, user: User):
    lesson = lesson_access(db, user, lesson_id, edit=True)
    versions = list(db.scalars(select(Curriculum).where(Curriculum.lesson_id == lesson.id)))
    version_ids = {version.id for version in versions}
    attempt_ids = set(db.scalars(select(Attempt.id).join(LearningSession, LearningSession.id == Attempt.session_id)
                               .where(LearningSession.curriculum_id.in_(version_ids))))
    affected = or_(Job.payload['lesson_id'].as_string() == lesson.id,
                   Job.payload['curriculum_id'].as_string().in_(version_ids),
                   Job.payload['attempt_id'].as_string().in_(attempt_ids))
    # Workers lock their job before their curriculum. NOWAIT avoids waiting on
    # a busy worker while deleting a lesson; no data is removed on a failed lock.
    for job in db.scalars(select(Job).where(affected).order_by(Job.id).with_for_update(nowait=True)):
        if job.state != 'completed':
            job.state, job.lease_until, job.fence = 'cancelled', None, job.fence + 1
            job.updated_at = time.time()
    lesson.retired = True
    for version in versions:
        version.publication, version.availability = 'retired', 'retired'
    audit(db, user, "lesson_retired", lesson.id)
    return {'deleted': True, 'retired': True, 'retained': 'Lesson records are archived; classroom assessment history is retained.'}


@router.get("/reviews/{curriculum_id}")
def review_detail(curriculum_id: str, db: DB, user: User):
    curriculum = curriculum_access(db, user, curriculum_id, edit=True)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if lesson.course_id:
        own_course(db, user, lesson.course_id)
    return {**curriculum_view(db, curriculum),
        "blocks": [{"id": x.id, "profile": x.profile, "objective_id": x.objective_id, "script": x.script, "verification": x.verification, "state": x.state} for x in db.scalars(select(Block).where(Block.curriculum_id == curriculum.id))],
        "assessments": [{"id": x.id, "objective_id": x.objective_id, "variant": x.variant, "question": x.public, "key": x.private, "validated": x.validated} for x in db.scalars(select(Assessment).where(Assessment.curriculum_id == curriculum.id))]}


def publication_ready(db, curriculum):
    if not curriculum.confirmed or curriculum.availability != "ready":
        raise HTTPException(409, "Every required block and checkpoint must be ready before classroom approval.")
    for objective in curriculum.blueprint["objectives"]:
        for profile in ("normal", "recap"):
            block = db.scalar(select(Block).where(Block.curriculum_id == curriculum.id, Block.objective_id == objective["id"], Block.profile == profile, Block.context_hash == "base"))
            if not block or block.state != "ready" or not block.verification.get("accepted"):
                raise HTTPException(409, "A required block or recap is not verified and ready.")
            assets = db.scalars(select(Asset).where(Asset.block_id == block.id)).all()
            expected = len(block.script.get("scenes", []))
            if not expected or sum(x.kind == "clip" for x in assets) != expected or sum(x.kind == "caption" for x in assets) != expected:
                raise HTTPException(409, "A required clip or caption is missing.")
        questions = db.scalars(select(Assessment).where(Assessment.curriculum_id == curriculum.id, Assessment.objective_id == objective["id"])).all()
        if len(questions) != 2 or not all(x.validated for x in questions):
            raise HTTPException(409, "The base and equivalent checks must be validated.")


@router.post("/reviews/{curriculum_id}/approve")
def approve(curriculum_id: str, body: ReviewInput, db: DB, user: User):
    curriculum = curriculum_access(db, user, curriculum_id, edit=True)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if user.privilege not in {"teacher", "administrator"} or not lesson.course_id:
        raise HTTPException(403, "Classroom approval requires a verified teacher and a course draft.")
    own_course(db, user, lesson.course_id)
    publication_ready(db, curriculum)
    actual = fingerprint(db, curriculum)
    if actual != body.expected_fingerprint:
        raise HTTPException(409, "The reviewed content changed. Review the new version.")
    if not all((body.coverage, body.factual, body.assessments, body.media)):
        raise HTTPException(409, "Coverage, facts, assessments, and rendered media all require review.")
    db.add(Review(curriculum_id=curriculum.id, reviewer_id=user.id, fingerprint=actual, approved=True, findings=body.model_dump()))
    curriculum.publication = "approved"
    audit(db, user, "lesson_approved", curriculum.id, fingerprint=actual)
    return {"publication": "approved", "fingerprint": actual}


@router.post("/reviews/{curriculum_id}/publish")
def publish(curriculum_id: str, db: DB, user: User):
    curriculum = curriculum_access(db, user, curriculum_id, edit=True)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if not lesson.course_id:
        raise HTTPException(409, "Only classroom drafts use classroom publication.")
    own_course(db, user, lesson.course_id)
    publication_ready(db, curriculum)
    actual = fingerprint(db, curriculum)
    review = db.scalar(select(Review).where(Review.curriculum_id == curriculum.id, Review.fingerprint == actual, Review.approved.is_(True)))
    if not review or curriculum.publication not in {"approved", "published"}:
        raise HTTPException(409, "Approval of this exact immutable version is required.")
    curriculum.publication = "published"
    audit(db, user, "lesson_published", curriculum.id)
    return {"publication": "published"}


@router.post("/reviews/{curriculum_id}/unpublish")
def unpublish(curriculum_id: str, db: DB, user: User):
    curriculum = curriculum_access(db, user, curriculum_id, edit=True)
    lesson = db.get(Lesson, curriculum.lesson_id)
    own_course(db, user, lesson.course_id)
    curriculum.publication = "suspended"
    audit(db, user, "lesson_suspended", curriculum.id)
    return {"publication": "suspended"}


@router.post("/courses/{course_id}/assignments", status_code=201)
def assign(course_id: str, body: AssignmentInput, db: DB, user: User):
    own_course(db, user, course_id)
    curriculum = curriculum_access(db, user, body.curriculum_id, edit=True)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if lesson.course_id != course_id or curriculum.publication != "published":
        raise HTTPException(409, "Assign a published lesson from this course.")
    assignment = Assignment(course_id=course_id, curriculum_id=curriculum.id, due_at=body.due_at)
    db.add(assignment)
    db.flush()
    audit(db, user, "lesson_assigned", assignment.id)
    return {"id": assignment.id}


@router.get("/courses/{course_id}/assignments")
def assignments(course_id: str, db: DB, user: User):
    course = db.get(Course, course_id)
    if not course or (course.owner_id != user.id and not enrolled(db, user.id, course_id)):
        raise HTTPException(404, "Course not found.")
    rows = db.execute(select(Assignment, Curriculum, Lesson).join(Curriculum, Curriculum.id == Assignment.curriculum_id).join(Lesson, Lesson.id == Curriculum.lesson_id).where(Assignment.course_id == course_id, Curriculum.publication == "published"))
    return [{"id": assignment.id, "title": lesson.title, "curriculum_id": version.id, "due_at": assignment.due_at} for assignment, version, lesson in rows]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: DB, user: User):
    job = db.get(Job, job_id)
    if not job or job.owner_id != user.id:
        raise HTTPException(404, "Preparation job not found.")
    history = db.scalars(select(Job).where(Job.owner_id == user.id, Job.state == 'completed', Job.kind == job.kind)
                         .order_by(Job.updated_at.desc()).limit(30)).all()
    return job_view(db, job, history)


def job_view(db, job, history):
    lesson_id = job.payload.get('lesson_id')
    curriculum = db.get(Curriculum, job.payload['curriculum_id']) if job.payload.get('curriculum_id') else None
    if curriculum:
        lesson_id = curriculum.lesson_id
    lesson = db.get(Lesson, lesson_id) if lesson_id else None
    return {"id": job.id, "kind": job.kind, "state": job.state, "stage": job.stage,
            "error_code": job.error_code, "result": {k: v for k, v in job.result.items() if not k.startswith('_')},
            "created_at": job.created_at, "updated_at": job.updated_at,
            "lesson_id": lesson_id, "course_id": lesson.course_id if lesson else None,
            'lesson_retired': bool(lesson and lesson.retired),
            "title": lesson.title if lesson else None, "eta": estimate(job, history, units=workload(db, job))}


@router.get("/jobs")
def job_list(db: DB, user: User):
    rows = db.scalars(select(Job).where(Job.owner_id == user.id).order_by(Job.created_at.desc()).limit(100)).all()
    history = db.scalars(select(Job).where(Job.owner_id == user.id, Job.state == 'completed')
                         .order_by(Job.updated_at.desc()).limit(100)).all()
    return [packet for job in rows if not (packet := job_view(db, job, history))['lesson_retired']]


@router.get("/reviews/{curriculum_id}/blocks/{block_id}/assets")
def preview_assets(curriculum_id: str, block_id: str, request: Request, db: DB, user: User):
    curriculum_access(db, user, curriculum_id, edit=True)
    block = db.get(Block, block_id)
    if not block or block.curriculum_id != curriculum_id or block.state != "ready":
        raise HTTPException(404, "The block is not ready for media review.")
    assets = db.scalars(select(Asset).where(Asset.block_id == block_id).order_by(Asset.position)).all()
    captions = {x.position: x for x in assets if x.kind == "caption"}
    return [{"id": x.id, "url": request.app.state.objects.sign(x.object_key), "transcript": x.transcript,
             "caption_url": request.app.state.objects.sign(captions[x.position].object_key) if x.position in captions else None}
            for x in assets if x.kind == "clip"]


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: DB, user: User):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_id == user.id).with_for_update())
    if not job:
        raise HTTPException(404, "Preparation job not found.")
    if job.state not in {"completed", "cancelled"}:
        job.state, job.lease_until, job.fence = "cancelled", None, job.fence + 1
        if job.kind == "grade":
            attempt = db.get(Attempt, job.payload.get("attempt_id"))
            if attempt and attempt.state != "graded":
                session = db.scalar(select(LearningSession).where(LearningSession.id == attempt.session_id).with_for_update())
                attempt.state, attempt.result = "service_failed", {"feedback": "Grading was cancelled. Your code is saved; retry when ready.", "error_code": "CANCELLED"}
                if session and session.route_revision == attempt.route_revision:
                    session.state = "checkpoint"
    return {"state": job.state}


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request, db: DB, user: User):
    admission_lock(db)
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_id == user.id).with_for_update(nowait=True))
    if not job:
        raise HTTPException(404, "Preparation job not found.")
    if job.state not in {"failed", "cancelled", "waiting_for_input", "waiting_for_review"}:
        raise HTTPException(409, "Only stopped jobs can be retried.")
    if job_view(db, job, [])['lesson_retired']:
        raise HTTPException(409, 'This lesson was deleted. Its preparation cannot be retried.')
    if job.kind == "grade":
        raise HTTPException(409, "Retry saved grading from its learning checkpoint.")
    requeue(db, request.app.state.settings, job)
    return {"id": job.id, "state": job.state}


@router.post("/issues", status_code=201)
def issue(body: IssueInput, db: DB, user: User):
    curriculum_access(db, user, body.curriculum_id)
    record = Issue(user_id=user.id, **body.model_dump())
    db.add(record)
    db.flush()
    return {"id": record.id}
