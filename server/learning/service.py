from fastapi import HTTPException
from sqlalchemy import select

from server.database import Assessment, Asset, Attempt, Block, Curriculum, Job, LearningSession, Lesson
from server.lessons.contracts import digest
from server.worker.queue import enqueue


def locked_session(db, user, session_id):
    session = db.scalar(select(LearningSession).where(LearningSession.id == session_id).with_for_update())
    if not session or session.user_id != user.id:
        raise HTTPException(404, "Learning session not found.")
    curriculum = db.get(Curriculum, session.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if lesson.retired:
        raise HTTPException(409, "This lesson has been retired. Your saved progress is retained.")
    if lesson.course_id:
        from server.auth import enrolled
        if curriculum.publication != "published" or not enrolled(db, user.id, lesson.course_id):
            raise HTTPException(403, "This assignment is unavailable or your course membership was revoked.")
    return session


def required_blocks(db, curriculum_id):
    return db.scalars(select(Block).where(Block.curriculum_id == curriculum_id, Block.context_hash == "base")).all()


def ready_for_objective(db, curriculum_id, objective_id, *, profile="normal", context_hash="base"):
    return db.scalar(select(Block).where(Block.curriculum_id == curriculum_id, Block.objective_id == objective_id,
                     Block.profile == profile, Block.context_hash == context_hash, Block.state == "ready"))


def current_question(db, session):
    question = db.scalar(select(Assessment).where(Assessment.curriculum_id == session.curriculum_id,
                         Assessment.objective_id == session.objective_id, Assessment.variant == session.variant))
    return {"id": question.id, **question.public} if question else None


def view_session(db, session):
    curriculum = db.get(Curriculum, session.curriculum_id)
    clips = []
    if session.selected_block_id:
        # Scene scripts hold no answer keys; the browser animates them (Remotion).
        scenes = (db.get(Block, session.selected_block_id).script or {}).get("scenes", [])
        clips = [{"id": x.id, "position": x.position, "duration": x.duration, "transcript": x.transcript, "mime": x.mime,
                  "scene": scenes[x.position] if x.position < len(scenes) else None}
                 for x in db.scalars(select(Asset).where(Asset.block_id == session.selected_block_id, Asset.kind == "clip").order_by(Asset.position))]
    latest = db.scalar(select(Attempt).where(Attempt.session_id == session.id).order_by(Attempt.created_at.desc()).limit(1))
    pending = latest if latest and latest.state in {"submitted", "running"} and latest.route_revision == session.route_revision else None
    return {"id": session.id, "curriculum_id": session.curriculum_id, "objective_id": session.objective_id,
            "active_attempt_id": pending.id if pending else None,
            "last_attempt": {"id": latest.id, "state": latest.state, "result": latest.result} if latest else None,
            "state": session.state, "revision": session.revision, "route_revision": session.route_revision,
            "selected_block_id": session.selected_block_id, "position": session.position, "evidence": session.evidence,
            "clips": clips, "question": current_question(db, session) if session.state == "checkpoint" else None,
            "objectives": curriculum.blueprint.get("objectives", []), "manifest_revision": session.manifest_revision,
            "continuation_job_id": session.continuation_job_id}


def select_objective(db, settings, session, objective_id, *, recap=False, misconception=None):
    curriculum = db.get(Curriculum, session.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    adapted_hash = (session.evidence.get(objective_id) or {}).get("adapted_hash")
    # Prefer anything already prepared so a learner never waits needlessly:
    # recap for a failed check; otherwise the block adapted to earlier results,
    # then a misconception-reinforced block, then the normal block.
    if recap:
        choices = [("recap", "base")]
    else:
        choices = ([("adapted", adapted_hash)] if adapted_hash else []) + (
            [("reinforced", digest({"misconception": misconception}))] if misconception else []) + [("normal", "base")]
    if lesson.course_id:
        # Classroom can choose only finite, reviewed variants; no live generation is published.
        choices = [x for x in choices if x[1] == "base"]
    block = next((b for profile, context_hash in choices
                  if (b := ready_for_objective(db, curriculum.id, objective_id, profile=profile, context_hash=context_hash))), None)
    profile, context_hash = choices[0]
    pending = None
    if block is None and adapted_hash and not recap:
        # The adapted block is already being prepared: wait for it rather than duplicating work.
        pending = db.scalar(select(Job).where(Job.kind == "block", Job.state.in_(["queued", "running"]),
            Job.payload["curriculum_id"].as_string() == curriculum.id, Job.payload["objective_id"].as_string() == objective_id,
            Job.payload["context_hash"].as_string() == adapted_hash).limit(1))
        if pending is None:
            profile, context_hash = "normal", "base"
    old_job = session.continuation_job_id
    session.objective_id, session.position = objective_id, {"clip": 0, "offset": 0}
    session.route_revision += 1
    session.manifest_revision = curriculum.manifest_revision
    if block:
        session.selected_block_id, session.state, session.continuation_job_id = block.id, "playing", None
    elif pending is not None:
        pending.priority = 0
        if session.id not in pending.consumers:
            pending.consumers = [*pending.consumers, session.id]
        session.selected_block_id, session.state, session.continuation_job_id = None, "waiting_for_block", pending.id
    elif lesson.course_id:
        session.selected_block_id, session.state, session.continuation_job_id = None, "recoverable_error", None
    else:
        payload = {"curriculum_id": curriculum.id, "objective_id": objective_id, "profile": profile,
                   "context_hash": context_hash, "misconception": misconception if profile == "reinforced" else None}
        try:
            job = enqueue(db, settings, lesson.owner_id, "block", payload, scope=f"private:{lesson.owner_id}:{curriculum.id}", priority=0, consumer=session.id)
            session.selected_block_id, session.state, session.continuation_job_id = None, "waiting_for_block", job.id
        except HTTPException as error:
            if error.status_code != 429:
                raise
            # A full preparation queue must not roll back a valid grade. Keep
            # the chosen route and its exact pending request available to retry.
            session.selected_block_id, session.state, session.continuation_job_id = None, "recoverable_error", None
            session.position = {**session.position, "pending_preparation": payload, "wait_reason": "preparation_queue_full"}
    if old_job and old_job != session.continuation_job_id:
        release_interest(db, old_job, session.id)
    for speculative in db.scalars(select(Job).where(Job.priority == 1, Job.state == "queued")):
        if session.id in speculative.consumers and speculative.id != session.continuation_job_id:
            release_interest(db, speculative.id, session.id)


def release_interest(db, job_id, session_id):
    job = db.get(Job, job_id)
    if job:
        job.consumers = [x for x in job.consumers if x != session_id]
        if not job.consumers and job.priority == 1 and job.state == "queued":
            job.state = "cancelled"


def settle_wait(db, session):
    if session.state != "waiting_for_block" or not session.continuation_job_id:
        return
    job = db.get(Job, session.continuation_job_id)
    if job.state == "completed":
        # Only the job selected by the current route can advance this session.
        block = db.get(Block, job.result.get("block_id"))
        if block and block.state == "ready" and block.objective_id == session.objective_id and block.curriculum_id == session.curriculum_id:
            session.selected_block_id, session.state, session.position = block.id, "playing", {"clip": 0, "offset": 0}
            session.manifest_revision = db.get(Curriculum, session.curriculum_id).manifest_revision
    elif job.state in {"failed", "cancelled", "waiting_for_input", "waiting_for_review"}:
        session.state = "recoverable_error"


def apply_grade(db, settings, session, attempt, result):
    if attempt.state == "graded":
        return attempt.result
    if attempt.route_revision != session.route_revision or session.state not in {"checkpoint", "submitting"}:
        attempt.state, attempt.result = "service_failed", {"feedback": "This answer belongs to a previous route. Your code is saved."}
        return attempt.result
    objective_id = session.objective_id
    entry = dict(session.evidence.get(objective_id, {}))
    entry["attempts"] = entry.get("attempts", 0) + 1
    entry.setdefault("first_attempt_passed", bool(result["passed"]))
    entry["misconception"] = result.get("misconception") or next(iter(result.get("failed_categories", [])), None) or entry.get("misconception")
    if result["passed"]:
        entry["status"] = "assisted" if entry.get("solution_shown") or entry.get("hint_assessment_id") == attempt.assessment_id else "passed"
    elif entry["attempts"] >= 3:
        entry["status"], entry["solution_shown"] = "unresolved", True
    else:
        entry["status"] = "needs_revision"
    session.evidence = {**session.evidence, objective_id: entry}
    if entry["attempts"] == 1:
        adapt_ahead(db, settings, session, objective_id)
    if result["passed"]:
        curriculum = db.get(Curriculum, session.curriculum_id)
        objectives = curriculum.blueprint["objectives"]
        index = next(i for i, item in enumerate(objectives) if item["id"] == objective_id)
        if index + 1 == len(objectives):
            statuses = [session.evidence.get(x["id"], {}).get("status") for x in objectives]
            session.state = "complete" if all(x == "passed" for x in statuses) else "complete_with_support" if all(x in {"passed", "assisted"} for x in statuses) else "needs_revision"
            session.route_revision += 1
        else:
            session.variant = "base"
            select_objective(db, settings, session, objectives[index + 1]["id"], misconception=entry.get("misconception"))
    elif entry["attempts"] >= 3:
        session.state, session.variant = "needs_revision", "equivalent"
        session.route_revision += 1
    else:
        session.variant = "equivalent"
        select_objective(db, settings, session, objective_id, recap=True)
    attempt.state = "graded"
    attempt.result = {**result, "objective_status": entry["status"], "route_revision": session.route_revision}
    if entry.get("solution_shown"):
        assessment = db.get(Assessment, attempt.assessment_id)
        attempt.result["worked_solution"] = assessment.private["explanation"]
        if assessment.public["kind"] == "python":
            attempt.result["reference_solution"] = assessment.private["reference_solution"]
    db.flush()
    if session.state == "playing":
        lookahead(db, settings, session)
    return attempt.result


def performance(session, objectives):
    """What the learner showed so far: drives the adapted block two objectives ahead."""
    titles = {x["id"]: x["title"] for x in objectives}
    rows = []
    for identifier, entry in session.evidence.items():
        if identifier in titles and entry.get("attempts"):
            rows.append({"objective": titles[identifier], "first_attempt_passed": entry.get("first_attempt_passed"),
                         "attempts": entry["attempts"], "status": entry.get("status"), "weak_point": entry.get("misconception")})
    return rows


def adapt_ahead(db, settings, session, objective_id):
    """After assessment k, prepare objective k+2 adapted to the learner (k+1 is already prepared)."""
    curriculum = db.get(Curriculum, session.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    objectives = curriculum.blueprint["objectives"]
    index = next(i for i, x in enumerate(objectives) if x["id"] == objective_id)
    if lesson.course_id or index + 2 >= len(objectives):
        return None
    target = objectives[index + 2]["id"]
    summary = performance(session, objectives)
    context_hash = digest({"performance": summary})
    entry = {**session.evidence.get(target, {}), "adapted_hash": context_hash}
    session.evidence = {**session.evidence, target: entry}
    if ready_for_objective(db, curriculum.id, target, profile="adapted", context_hash=context_hash):
        return None
    payload = {"curriculum_id": curriculum.id, "objective_id": target, "profile": "adapted", "context_hash": context_hash,
               "misconception": None, "performance": summary}
    try:
        return enqueue(db, settings, lesson.owner_id, "block", payload, scope=f"private:{lesson.owner_id}:{curriculum.id}", priority=1, consumer=session.id)
    except HTTPException as error:
        if error.status_code != 429:
            raise
        return None


def lookahead(db, settings, session):
    if not settings.speculation_enabled:
        return None
    curriculum = db.get(Curriculum, session.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if lesson.course_id or session.state != "playing":
        return None
    objectives = curriculum.blueprint["objectives"]
    index = next(i for i, x in enumerate(objectives) if x["id"] == session.objective_id)
    if index + 1 == len(objectives):
        return None
    if ready_for_objective(db, curriculum.id, objectives[index + 1]["id"]):
        return None
    # Speculation has no right to use the slot while a selected continuation waits.
    if db.scalar(select(Job.id).where(Job.state.in_(["running", "queued"]), Job.priority == 0).limit(1)):
        return None
    from server.database import AuditEvent
    import time
    from sqlalchemy import func
    used = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "model_call", AuditEvent.created_at >= time.time() - 86400))
    if used >= settings.daily_model_calls:
        return None
    payload = {"curriculum_id": curriculum.id, "objective_id": objectives[index + 1]["id"], "profile": "normal", "context_hash": "base", "misconception": None}
    try:
        return enqueue(db, settings, lesson.owner_id, "block", payload, scope=f"private:{lesson.owner_id}:{curriculum.id}", priority=1, consumer=session.id)
    except HTTPException as error:
        if error.status_code != 429:
            raise
        return None
