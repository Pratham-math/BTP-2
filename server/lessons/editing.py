"""Draft edits and forks preserve the versions pinned by existing learners."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import delete, func, select

from server.auth import curriculum_access, own_course
from server.database import Assessment, Asset, Block, Curriculum, LearningSession, Lesson
from server.lessons.contracts import BlockDraft, PlannedAssessment, digest
from server.platform_api import Body, DB, User, audit, fingerprint
from server.worker.queue import enqueue


router = APIRouter(prefix="/api/lessons/versions")


class Fork(Body):
    course_id: str | None = None
    title: str | None = Field(default=None, min_length=3, max_length=160)


class BlockEdit(Body):
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    draft: BlockDraft


class AssessmentEdit(Body):
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    definition: PlannedAssessment


def editable(db, user, curriculum_id, expected):
    curriculum = curriculum_access(db, user, curriculum_id, edit=True)
    if curriculum.publication != "draft":
        raise HTTPException(409, "Approved content is immutable. Fork a new draft version.")
    if db.scalar(select(LearningSession.id).where(LearningSession.curriculum_id == curriculum_id).limit(1)):
        raise HTTPException(409, "Learners have pinned this version. Fork a new version before editing.")
    if fingerprint(db, curriculum) != expected:
        raise HTTPException(409, "The draft changed. Reload the review packet before editing.")
    return curriculum


@router.post("/{curriculum_id}/fork", status_code=201)
def fork(curriculum_id: str, body: Fork, db: DB, user: User):
    previous = curriculum_access(db, user, curriculum_id, edit=True)
    old_lesson = db.get(Lesson, previous.lesson_id)
    target_course = body.course_id if body.course_id else old_lesson.course_id
    if target_course:
        own_course(db, user, target_course)
    if target_course != old_lesson.course_id:
        lesson = Lesson(owner_id=user.id, course_id=target_course, title=body.title or old_lesson.title)
        db.add(lesson); db.flush(); number = 1
    else:
        lesson = old_lesson
        # Serialize version allocation on its parent lesson.
        db.scalar(select(Lesson).where(Lesson.id == lesson.id).with_for_update())
        number = (db.scalar(select(func.max(Curriculum.number)).where(Curriculum.lesson_id == lesson.id)) or 0) + 1
    version = Curriculum(lesson_id=lesson.id, number=number, blueprint=previous.blueprint,
                          confirmed=previous.confirmed, availability=previous.availability, manifest_revision=previous.manifest_revision)
    db.add(version); db.flush()
    for old in db.scalars(select(Block).where(Block.curriculum_id == previous.id)):
        block = Block(curriculum_id=version.id, objective_id=old.objective_id, profile=old.profile, context_hash=old.context_hash,
                      state="rendering" if old.state == "ready" else old.state, script=old.script, verification=old.verification, checksum=old.checksum)
        db.add(block); db.flush()
        for asset in db.scalars(select(Asset).where(Asset.block_id == old.id)):
            db.add(Asset(block_id=block.id, position=asset.position, kind=asset.kind, object_key=asset.object_key,
                         checksum=asset.checksum, duration=asset.duration, mime=asset.mime, transcript=asset.transcript))
        db.flush()
        block.state = old.state
    for old in db.scalars(select(Assessment).where(Assessment.curriculum_id == previous.id)):
        db.add(Assessment(curriculum_id=version.id, objective_id=old.objective_id, variant=old.variant,
                          public=old.public, private=old.private, validated=old.validated))
    audit(db, user, "draft_forked", version.id, previous_version_id=previous.id)
    db.flush()
    return {"curriculum_id": version.id}


@router.patch("/{curriculum_id}/blocks/{block_id}", status_code=202)
def edit_block(curriculum_id: str, block_id: str, body: BlockEdit, request: Request, db: DB, user: User):
    curriculum = editable(db, user, curriculum_id, body.expected_fingerprint)
    block = db.get(Block, block_id)
    if not block or block.curriculum_id != curriculum.id:
        raise HTTPException(404, "Draft block not found.")
    draft = body.draft
    if draft.objective_id != block.objective_id or draft.profile != block.profile:
        raise HTTPException(422, "Edits must retain the fixed objective and block profile.")
    objective = next(x for x in curriculum.blueprint["objectives"] if x["id"] == block.objective_id)
    allowed = {(x["source_version_id"], x["block_id"]) for x in objective["evidence"]}
    if any((x.source_version_id, x.block_id) not in allowed for x in draft.source_refs):
        raise HTTPException(422, "The edited block cited evidence outside its objective.")
    block.state, block.script = "planned", draft.model_dump()
    block.verification, block.checksum = {"accepted": False, "manual_edit": True}, None
    db.flush()
    db.execute(delete(Asset).where(Asset.block_id == block.id))
    curriculum.availability = "needs_attention"
    lesson = db.get(Lesson, curriculum.lesson_id)
    payload = {"curriculum_id": curriculum.id, "objective_id": block.objective_id, "profile": block.profile,
               "context_hash": block.context_hash, "misconception": None, "manual_revision": digest(block.script)}
    job = enqueue(db, request.app.state.settings, lesson.owner_id, "block", payload, scope=f"private:{lesson.owner_id}:{curriculum.id}")
    audit(db, user, "block_edited", block.id)
    return {"job_id": job.id}


@router.patch("/{curriculum_id}/assessments/{assessment_id}", status_code=202)
def edit_assessment(curriculum_id: str, assessment_id: str, body: AssessmentEdit, request: Request, db: DB, user: User):
    curriculum = editable(db, user, curriculum_id, body.expected_fingerprint)
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.curriculum_id != curriculum.id:
        raise HTTPException(404, "Draft assessment not found.")
    definition = body.definition
    if definition.objective_id != assessment.objective_id or definition.variant != assessment.variant:
        raise HTTPException(422, "Edits cannot change the assessment's objective or variant.")
    assessment.public, assessment.private, assessment.validated = definition.question.model_dump(), definition.key.model_dump(), False
    lesson = db.get(Lesson, curriculum.lesson_id)
    job = enqueue(db, request.app.state.settings, lesson.owner_id, "validate_assessment",
                  {"assessment_id": assessment.id, "revision": digest(definition.model_dump())}, scope=f"private:{lesson.owner_id}:{curriculum.id}")
    audit(db, user, "assessment_edited", assessment.id)
    return {"job_id": job.id}
