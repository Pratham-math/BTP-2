import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StringConstraints
from sqlalchemy import delete, select

from server.auth import curriculum_access, enrolled, own_course
from server.database import (Assessment, Asset, Assignment, Attempt, Block, Course,
    Curriculum, Job, LearningSession, Lesson, Profile, StageResult)
from server.lessons.contracts import digest
from server.learning.service import (apply_grade, current_question, locked_session, lookahead,
    ready_for_objective, select_objective, settle_wait, view_session)
from server.platform_api import Body, DB, User
from server.worker.queue import admission_lock, enqueue, requeue


router = APIRouter(prefix="/api")


class StartSession(Body):
    curriculum_id: str
    assignment_id: str | None = None


class Progress(Body):
    expected_revision: int = Field(ge=1)
    route_revision: int = Field(ge=1)
    block_id: str
    clip: int = Field(ge=0)
    offset: float = Field(ge=0, le=3600)
    ended: bool = False
    code_draft: str | None = Field(default=None, max_length=16000)


class Answer(Body):
    session_id: str
    assessment_id: str
    route_revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    answer: dict = Field(max_length=3)


class RouteInput(Body):
    expected_revision: int = Field(ge=1)


class CodeDraft(RouteInput):
    route_revision: int = Field(ge=1)
    assessment_id: str
    code: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(max_length=16000)


class RevisionRoute(RouteInput):
    prerequisite_id: str | None = None


@router.get("/sessions")
def session_list(db: DB, user: User):
    rows = db.execute(select(LearningSession, Lesson, Curriculum).join(Curriculum, Curriculum.id == LearningSession.curriculum_id).join(Lesson, Lesson.id == Curriculum.lesson_id).where(LearningSession.user_id == user.id, Lesson.retired.is_(False)).order_by(LearningSession.created_at.desc()).limit(100))
    return [{"id": session.id, "title": lesson.title, "state": session.state, "objective_id": session.objective_id,
             "course_id": lesson.course_id, "assignment_id": session.assignment_id, "curriculum_id": curriculum.id,
             "total_objectives": len(curriculum.blueprint.get('objectives', [])),
             "covered_objectives": sum(x.get('status') in {'passed', 'assisted', 'unresolved'} for x in session.evidence.values()),
             "passed_objectives": sum(x.get('status') == 'passed' for x in session.evidence.values())}
            for session, lesson, curriculum in rows]


@router.post("/sessions", status_code=201)
def start(body: StartSession, request: Request, db: DB, user: User):
    # Serialize session pinning with draft edits and publication decisions.
    db.scalar(select(Curriculum).where(Curriculum.id == body.curriculum_id).with_for_update())
    curriculum = curriculum_access(db, user, body.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if not curriculum.confirmed:
        raise HTTPException(409, "Confirm the complete curriculum before starting.")
    if lesson.course_id:
        assignment = db.get(Assignment, body.assignment_id) if body.assignment_id else None
        if not assignment or assignment.curriculum_id != curriculum.id or assignment.course_id != lesson.course_id or not enrolled(db, user.id, lesson.course_id):
            raise HTTPException(403, "Start this lesson through an enrolled classroom assignment.")
        if curriculum.publication != "published":
            raise HTTPException(409, "This classroom version is not published.")
    elif body.assignment_id:
        raise HTTPException(422, "Independent lessons do not have classroom assignments.")
    from server.worker.queue import admission_lock
    admission_lock(db)
    previous = db.scalar(select(LearningSession).where(LearningSession.user_id == user.id, LearningSession.curriculum_id == curriculum.id,
                         LearningSession.assignment_id == body.assignment_id).order_by(LearningSession.created_at.desc()).limit(1))
    if previous:
        return view_session(db, previous)
    first = curriculum.blueprint["objectives"][0]["id"]
    block = ready_for_objective(db, curriculum.id, first)
    recap = ready_for_objective(db, curriculum.id, first, profile="recap")
    questions = db.scalars(select(Assessment).where(Assessment.curriculum_id == curriculum.id, Assessment.objective_id == first)).all()
    if not block or not recap or len(questions) != 2 or not all(x.validated for x in questions):
        raise HTTPException(409, "The first complete block, recap, and validated checks are still preparing.")
    session = LearningSession(user_id=user.id, curriculum_id=curriculum.id, assignment_id=body.assignment_id,
                              selected_block_id=block.id, objective_id=first, state="playing",
                              position={"clip": 0, "offset": 0}, evidence={}, manifest_revision=curriculum.manifest_revision)
    db.add(session)
    db.flush()
    lookahead(db, request.app.state.settings, session)
    return view_session(db, session)


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, request: Request, db: DB, user: User):
    session = locked_session(db, user, session_id)
    lookahead(db, request.app.state.settings, session)
    settle_wait(db, session)
    db.flush()
    return view_session(db, session)


@router.patch("/sessions/{session_id}/progress")
def progress(session_id: str, body: Progress, request: Request, db: DB, user: User):
    session = locked_session(db, user, session_id)
    if session.revision != body.expected_revision or session.route_revision != body.route_revision or session.selected_block_id != body.block_id:
        raise HTTPException(409, "Progress changed in another tab. Reload the saved session.")
    if session.state not in {"playing", "checkpoint"}:
        raise HTTPException(409, "This route cannot accept playback progress.")
    clips = db.scalars(select(Asset).where(Asset.block_id == session.selected_block_id, Asset.kind == "clip").order_by(Asset.position)).all()
    current = session.position.get("clip", 0)
    if body.clip != current or body.clip >= len(clips):
        raise HTTPException(409, "Save progress for the selected scene before advancing.")
    if body.offset > clips[current].duration + 1:
        raise HTTPException(422, "Playback offset exceeds this clip's duration.")
    position = {**session.position, "clip": body.clip, "offset": body.offset, "last_seen": time.time()}
    if body.code_draft is not None:
        position["code_draft"] = body.code_draft
    if body.ended:
        if current + 1 < len(clips):
            position.update(clip=current + 1, offset=0)
        elif session.position.get("reviewing_prerequisite"):
            # A prerequisite replay is teaching support, not another compulsory
            # assessment. Rejoin the selected objective's recap and fresh check.
            select_objective(db, request.app.state.settings, session, session.objective_id, recap=True)
            db.flush()
            return view_session(db, session)
        else:
            session.state = "checkpoint"
            entry = dict(session.evidence.get(session.objective_id, {}))
            entry["viewed"] = True
            session.evidence = {**session.evidence, session.objective_id: entry}
    session.position = position
    lookahead(db, request.app.state.settings, session)
    db.flush()
    return view_session(db, session)


@router.post("/sessions/{session_id}/hint")
def hint(session_id: str, body: RouteInput, db: DB, user: User):
    session = locked_session(db, user, session_id)
    if session.state != "checkpoint" or session.revision != body.expected_revision:
        raise HTTPException(409, "Reload the current checkpoint before requesting a hint.")
    question = current_question(db, session)
    assessment = db.get(Assessment, question["id"])
    entry = dict(session.evidence.get(session.objective_id, {}))
    used = entry.get("hints_used", 0)
    hints = assessment.private["hints"]
    selected = hints[min(used, len(hints) - 1)]
    entry["hints_used"] = min(used + 1, len(hints))
    entry["hint_assessment_id"] = assessment.id
    session.evidence = {**session.evidence, session.objective_id: entry}
    db.flush()
    return {"hint": selected, "level": entry["hints_used"], "revision": session.revision}


@router.patch("/sessions/{session_id}/draft")
def save_draft(session_id: str, body: CodeDraft, db: DB, user: User):
    session = locked_session(db, user, session_id)
    if session.state != "checkpoint" or session.revision != body.expected_revision or session.route_revision != body.route_revision:
        raise HTTPException(409, "The checkpoint changed. Your local code draft is retained; reload before saving.")
    question = current_question(db, session)
    if not question or question["kind"] != "python" or question["id"] != body.assessment_id:
        raise HTTPException(409, "Save code only for the selected Python checkpoint.")
    session.position = {**session.position, "code_draft": body.code}
    db.flush()
    return view_session(db, session)


@router.post("/attempts", status_code=202)
def submit(body: Answer, request: Request, db: DB, user: User):
    from server.assessment.grading import grade
    # An idempotent replay is checked before current route/revision, because a
    # successful first request advances those fields atomically with its grade.
    signature = digest(body.model_dump(exclude={"idempotency_key"}))
    previous = db.scalar(select(Attempt).where(Attempt.user_id == user.id, Attempt.idempotency_key == body.idempotency_key))
    if previous:
        if previous.request_hash != signature:
            raise HTTPException(409, "This submission ID was used with a different answer.")
        return {"id": previous.id, "state": previous.state, "result": previous.result}
    session = locked_session(db, user, body.session_id)
    # Recheck after the session lock to cover simultaneous duplicate requests.
    previous = db.scalar(select(Attempt).where(Attempt.user_id == user.id, Attempt.idempotency_key == body.idempotency_key))
    if previous:
        if previous.request_hash != signature:
            raise HTTPException(409, "This submission ID was used with a different answer.")
        return {"id": previous.id, "state": previous.state, "result": previous.result}
    if session.state != "checkpoint" or session.route_revision != body.route_revision or session.revision != body.expected_revision:
        raise HTTPException(409, "This checkpoint changed. Reload before submitting.")
    question = current_question(db, session)
    if not question or question["id"] != body.assessment_id:
        raise HTTPException(409, "Only the current checkpoint can be submitted.")
    assessment = db.get(Assessment, body.assessment_id)
    if not assessment.validated:
        raise HTTPException(409, "This assessment has not passed validation.")
    # Bounded payload even if a client bypasses editor limits.
    if len(str(body.answer)) > 18000:
        raise HTTPException(422, "The answer exceeds the submission size limit.")
    attempt = Attempt(user_id=user.id, session_id=session.id, assessment_id=assessment.id,
                      idempotency_key=body.idempotency_key, request_hash=signature, answer=body.answer,
                      route_revision=session.route_revision)
    db.add(attempt)
    db.flush()
    if assessment.public["kind"] in {"python", "short"}:
        if assessment.public["kind"] == "python":
            request.app.state.runner.ready()
            code = body.answer.get("code")
            if not isinstance(code, str) or not code.strip() or len(code) > 16000:
                raise HTTPException(422, "Enter between 1 and 16000 characters of Python code.")
            session.position = {**session.position, "code_draft": code}
        else:
            text = body.answer.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise HTTPException(422, "Write an answer of up to 4000 characters.")
        enqueue(db, request.app.state.settings, user.id, "grade", {"attempt_id": attempt.id}, scope=f"private:{user.id}", priority=0)
        session.state = "submitting"
    else:
        try:
            result = grade(assessment.public, assessment.private, body.answer)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        apply_grade(db, request.app.state.settings, session, attempt, result)
    return {"id": attempt.id, "state": attempt.state, "result": attempt.result}


@router.get("/attempts/{attempt_id}")
def attempt_detail(attempt_id: str, db: DB, user: User):
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "Attempt not found.")
    return {"id": attempt.id, "state": attempt.state, "result": attempt.result}


@router.post("/attempts/{attempt_id}/retry", status_code=202)
def retry_grading(attempt_id: str, request: Request, db: DB, user: User):
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "Attempt not found.")
    # Workers/cancellation take the job lock before the session lock. Keep that
    # order on retry, so a finishing worker cannot deadlock against this route.
    admission_lock(db)
    job = db.scalar(select(Job).where(Job.dedup_key == digest({"scope": f"private:{user.id}", "kind": "grade", "payload": {"attempt_id": attempt.id}, "schema": 1})).with_for_update(nowait=True))
    session = locked_session(db, user, attempt.session_id)
    if attempt.state != "service_failed" or attempt.route_revision != session.route_revision or (job and job.state not in {"failed", "cancelled", "waiting_for_input", "waiting_for_review"}):
        raise HTTPException(409, "Only a grading-service failure on the current route can be retried.")
    request.app.state.runner.ready()
    if job:
        requeue(db, request.app.state.settings, job)
        # A provider's permanently failed token must not be reused forever on
        # an explicit retry. The attempt itself remains a single durable record.
        db.execute(delete(StageResult).where(StageResult.job_id == job.id, StageResult.stage == "runner_tokens"))
    else:
        enqueue(db, request.app.state.settings, user.id, "grade", {"attempt_id": attempt.id}, scope=f"private:{user.id}", priority=0)
    attempt.state, attempt.result, session.state = "submitted", {}, "submitting"
    return {"id": attempt.id, "state": attempt.state}


@router.get("/sessions/{session_id}/continuation")
def continuation(session_id: str, request: Request, db: DB, user: User):
    session = locked_session(db, user, session_id)
    lookahead(db, request.app.state.settings, session)
    settle_wait(db, session)
    job = db.get(Job, session.continuation_job_id) if session.continuation_job_id else None
    status = "ready" if session.state == "playing" else "blocked" if session.state == "recoverable_error" else "preparing"
    fallback = ready_for_objective(db, session.curriculum_id, session.objective_id, profile="recap")
    db.flush()
    return {"status": status, "route_revision": session.route_revision, "job_stage": job.stage if job else None,
            "error_code": job.error_code if job else None, "fallback_block_id": fallback.id if fallback else None,
            "session": view_session(db, session)}


@router.get("/sessions/{session_id}/fallback")
def fallback_access(session_id: str, request: Request, db: DB, user: User):
    session = locked_session(db, user, session_id)
    block = ready_for_objective(db, session.curriculum_id, session.objective_id, profile="recap")
    if not block:
        raise HTTPException(409, "A relevant recap is not ready. You can save and return later.")
    scenes = (block.script or {}).get("scenes", [])
    captions = {x.position: x for x in db.scalars(select(Asset).where(Asset.block_id == block.id, Asset.kind == "caption"))}
    return {"block_id": block.id, "clips": [{"id": x.id, "url": request.app.state.objects.sign(x.object_key), "mime": x.mime, "duration": x.duration,
        "scene": scenes[x.position] if x.position < len(scenes) else None,
        "caption": request.app.state.objects.sign(captions[x.position].object_key) if x.position in captions else None}
        for x in db.scalars(select(Asset).where(Asset.block_id == block.id, Asset.kind == "clip").order_by(Asset.position))]}


@router.post("/sessions/{session_id}/resume-continuation", status_code=202)
def resume_continuation(session_id: str, body: RouteInput, request: Request, db: DB, user: User):
    session = locked_session(db, user, session_id)
    if session.revision != body.expected_revision or session.state != "recoverable_error":
        raise HTTPException(409, "Reload the current continuation before retrying.")
    admission_lock(db)
    job = db.scalar(select(Job).where(Job.id == session.continuation_job_id).with_for_update(nowait=True))
    pending = session.position.get("pending_preparation")
    if not job and pending:
        curriculum = db.get(Curriculum, session.curriculum_id)
        lesson = db.get(Lesson, curriculum.lesson_id)
        if lesson.course_id or lesson.owner_id != user.id or pending.get("curriculum_id") != curriculum.id or pending.get("objective_id") != session.objective_id:
            raise HTTPException(409, "This continuation requires teacher or operator attention.")
        job = enqueue(db, request.app.state.settings, user.id, "block", pending, scope=f"private:{user.id}:{curriculum.id}", priority=0, consumer=session.id)
        session.continuation_job_id = job.id
        session.position = {"clip": 0, "offset": 0}
    if not job or job.owner_id != user.id or job.kind != "block" or job.payload.get("curriculum_id") != session.curriculum_id or job.payload.get("objective_id") != session.objective_id:
        raise HTTPException(409, "This continuation requires teacher or operator attention.")
    if job.state in {"failed", "cancelled", "waiting_for_input", "waiting_for_review"}:
        requeue(db, request.app.state.settings, job)
    session.state = "waiting_for_block"
    db.flush()
    return view_session(db, session)


@router.post("/sessions/{session_id}/revision-route")
def revision_route(session_id: str, body: RevisionRoute, request: Request, db: DB, user: User):
    session = locked_session(db, user, session_id)
    if session.revision != body.expected_revision or session.state != "needs_revision":
        raise HTTPException(409, "Reload the revision route before continuing.")
    session.variant = "equivalent"
    objective_id = session.objective_id
    if body.prerequisite_id:
        curriculum = db.get(Curriculum, session.curriculum_id)
        objective = next(x for x in curriculum.blueprint["objectives"] if x["id"] == objective_id)
        if body.prerequisite_id not in objective["prerequisites"]:
            raise HTTPException(422, "Choose a direct prerequisite from this objective's fixed curriculum.")
        if not ready_for_objective(db, curriculum.id, body.prerequisite_id, profile="recap"):
            raise HTTPException(409, "That prerequisite recap is not ready. Review the current concept instead.")
        select_objective(db, request.app.state.settings, session, body.prerequisite_id, recap=True)
        session.objective_id = objective_id
        session.position = {**session.position, "reviewing_prerequisite": body.prerequisite_id}
    else:
        select_objective(db, request.app.state.settings, session, objective_id, recap=True)
    db.flush()
    return view_session(db, session)


@router.get("/assets/{asset_id}/access")
def asset_access(asset_id: str, request: Request, db: DB, user: User, session_id: str | None = None):
    asset = db.get(Asset, asset_id)
    block = db.get(Block, asset.block_id) if asset else None
    if not block or block.state != "ready":
        raise HTTPException(404, "Asset not found.")
    curriculum = db.get(Curriculum, block.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if lesson.owner_id != user.id:
        if not session_id:
            raise HTTPException(404, "Asset not found.")
        session = locked_session(db, user, session_id)
        fallback = ready_for_objective(db, session.curriculum_id, session.objective_id, profile="recap")
        if block.id != session.selected_block_id and (not fallback or block.id != fallback.id):
            raise HTTPException(404, "Asset not found.")
        if session.curriculum_id != curriculum.id:
            raise HTTPException(404, "Asset not found.")
    else:
        curriculum_access(db, user, curriculum.id)
    # Never issue access for a block under production or a suspended classroom.
    if lesson.course_id and curriculum.publication != "published" and lesson.owner_id != user.id:
        raise HTTPException(404, "Asset not found.")
    return {"url": request.app.state.objects.sign(asset.object_key), "expires_at": time.time() + 300,
            "checksum": asset.checksum, "mime": asset.mime}


@router.get("/sessions/{session_id}/captions/{asset_id}")
def caption_access(session_id: str, asset_id: str, request: Request, db: DB, user: User):
    session = locked_session(db, user, session_id)
    asset = db.get(Asset, asset_id)
    if not asset or asset.block_id != session.selected_block_id or asset.kind != "clip":
        raise HTTPException(404, "Caption not found.")
    caption = db.scalar(select(Asset).where(Asset.block_id == asset.block_id, Asset.position == asset.position, Asset.kind == "caption"))
    if not caption:
        raise HTTPException(404, "Caption not found.")
    return {"url": request.app.state.objects.sign(caption.object_key), "expires_at": time.time() + 300}


@router.get("/reports/me")
def own_report(db: DB, user: User):
    return [{"id": x.id, "curriculum_id": x.curriculum_id, "state": x.state, "evidence": x.evidence}
            for x in db.scalars(select(LearningSession).join(Curriculum, Curriculum.id == LearningSession.curriculum_id)
                .join(Lesson, Lesson.id == Curriculum.lesson_id).where(LearningSession.user_id == user.id, Lesson.retired.is_(False)))]


@router.get("/reports/courses/{course_id}")
def course_report(course_id: str, db: DB, user: User):
    own_course(db, user, course_id)
    rows = db.execute(select(LearningSession, Profile, Lesson).join(Assignment, Assignment.id == LearningSession.assignment_id)
        .join(Profile, Profile.id == LearningSession.user_id).join(Curriculum, Curriculum.id == LearningSession.curriculum_id)
        .join(Lesson, Lesson.id == Curriculum.lesson_id).where(Assignment.course_id == course_id))
    return [{"session_id": session.id, "learner": profile.display_name, "state": session.state,
             'lesson_title': lesson.title, 'archived': lesson.retired, "evidence": session.evidence}
            for session, profile, lesson in rows]
