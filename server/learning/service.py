from fastapi import HTTPException
from sqlalchemy import select

from server.database import Assessment, Asset, Attempt, Block, Curriculum, Job, LearningSession, Lesson
from server.lessons.contracts import digest
from server.worker.queue import enqueue
from server.learning.adaptation import LEAD, VERSION, bounded_score, understanding


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
            "continuation_job_id": session.continuation_job_id,
            "adaptivity": adaptive_view(db, session, curriculum)}


def select_objective(db, settings, session, objective_id, *, recap=False, misconception=None):
    curriculum = db.get(Curriculum, session.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    index = next(i for i, item in enumerate(curriculum.blueprint['objectives']) if item['id'] == objective_id)
    if not lesson.course_id and not recap and index >= LEAD and not session.evidence.get(objective_id, {}).get('adaptive_plan'):
        source = curriculum.blueprint['objectives'][index - LEAD]['id']
        if session.evidence.get(source, {}).get('attempts'):
            adapt_ahead(db, settings, session, source)
    adapted_hash = (session.evidence.get(objective_id) or {}).get("adapted_hash")
    plan = (session.evidence.get(objective_id) or {}).get('adaptive_plan') if not lesson.course_id and not recap else None
    # Initial blocks stay normal; recaps handle failed checks. A committed
    # adaptive plan must be played rather than silently bypassed by a base clip.
    if recap:
        choices = [("recap", "base")]
    else:
        choices = ([("adapted", adapted_hash)] if adapted_hash else []) + (
            [("reinforced", digest({"misconception": misconception}))] if misconception else []) + [("normal", "base")]
    if lesson.course_id:
        # Classroom can choose only finite, reviewed variants; no live generation is published.
        choices = [x for x in choices if x[1] == "base"]
    if plan:
        choices = [('adapted', adapted_hash)]
    elif not lesson.course_id and not recap and index < LEAD:
        choices = [('normal', 'base')]
        adapted_hash = None
    block = next((b for profile, context_hash in choices
                  if (b := ready_for_objective(db, curriculum.id, objective_id, profile=profile, context_hash=context_hash))), None)
    profile, context_hash = choices[0]
    pending = None
    if block is None and adapted_hash and not recap:
        # The adapted block is already being prepared: wait for it rather than duplicating work.
        pending = db.scalar(select(Job).where(Job.kind == "block", Job.state.in_(["queued", "running"]),
            Job.payload["curriculum_id"].as_string() == curriculum.id, Job.payload["objective_id"].as_string() == objective_id,
            Job.payload["context_hash"].as_string() == adapted_hash).limit(1))
        if pending is None and not plan:
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
        if plan:
            payload = plan
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
    entry.setdefault('first_score', bounded_score(result.get('score'), float(bool(result['passed']))))
    entry['latest_score'] = bounded_score(result.get('score'), float(bool(result['passed'])))
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


def performance(session, objectives, *, through=None):
    rows = []
    for index, objective in enumerate(objectives):
        if through is not None and index > through:
            break
        entry = session.evidence.get(objective['id'], {})
        if entry.get('attempts'):
            rows.append({'objective': objective['title'], 'first_attempt_passed': entry.get('first_attempt_passed'),
                         'attempts': entry['attempts'], 'status': entry.get('status'),
                         'hints_used': entry.get('hints_used', 0), 'solution_shown': bool(entry.get('solution_shown')),
                         'first_score': entry.get('first_score'), 'latest_score': entry.get('latest_score'),
                         'weak_point': entry.get('misconception')})
    return rows[-5:]


def enqueue_initial_window(db, settings, curriculum, lesson, *, consumer=None):
    if lesson.course_id:
        return []
    jobs = []
    for objective in curriculum.blueprint['objectives'][1:LEAD]:
        if ready_for_objective(db, curriculum.id, objective['id']):
            continue
        payload = {'curriculum_id': curriculum.id, 'objective_id': objective['id'], 'profile': 'normal',
                   'context_hash': 'base', 'misconception': None}
        previous = db.scalar(select(Job).where(Job.owner_id == lesson.owner_id, Job.kind == 'block',
            Job.payload['curriculum_id'].as_string() == curriculum.id,
            Job.payload['objective_id'].as_string() == objective['id'],
            Job.payload['profile'].as_string() == 'normal', Job.payload['context_hash'].as_string() == 'base').limit(1))
        if previous:
            if previous.priority == 1 and previous.state == 'queued':
                previous.priority = 2
            jobs.append(previous)
            continue
        try:
            jobs.append(enqueue(db, settings, lesson.owner_id, 'block', payload,
                scope=f'private:{lesson.owner_id}:{curriculum.id}', priority=2, consumer=consumer))
        except HTTPException as error:
            if error.status_code != 429:
                raise
            break  # The session poll retries admission when capacity is available.
    return jobs


def adapt_ahead(db, settings, session, objective_id):
    """Assessment k fixes a teaching snapshot for block k+3, without rerendering on retries."""
    curriculum = db.get(Curriculum, session.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    objectives = curriculum.blueprint['objectives']
    index = next(i for i, x in enumerate(objectives) if x['id'] == objective_id)
    if lesson.course_id or index + LEAD >= len(objectives):
        return None
    target = objectives[index + LEAD]
    entry = dict(session.evidence.get(target['id'], {}))
    plan = entry.get('adaptive_plan')
    if not plan:
        summary = performance(session, objectives, through=index)
        adaptation = {**understanding(session.evidence, objectives, through=index, target=target),
                      'based_on_objective': objective_id, 'assessment_number': index + 1,
                      'target_number': index + LEAD + 1}
        context_hash = digest({'algorithm': VERSION, 'performance': summary, 'adaptation': adaptation})
        plan = {'curriculum_id': curriculum.id, 'objective_id': target['id'], 'profile': 'adapted',
                'context_hash': context_hash, 'misconception': None, 'performance': summary, 'adaptation': adaptation}
        entry.update(adapted_hash=context_hash, adaptive_plan=plan)
        session.evidence = {**session.evidence, target['id']: entry}
    if ready_for_objective(db, curriculum.id, target['id'], profile='adapted', context_hash=plan['context_hash']):
        return None
    previous = db.scalar(select(Job).where(Job.owner_id == lesson.owner_id, Job.kind == 'block',
        Job.payload['curriculum_id'].as_string() == curriculum.id,
        Job.payload['context_hash'].as_string() == plan['context_hash']).limit(1))
    if previous:
        return previous
    try:
        # This is requested rolling preparation, not disposable speculation.
        return enqueue(db, settings, lesson.owner_id, 'block', plan,
            scope=f'private:{lesson.owner_id}:{curriculum.id}', priority=2, consumer=session.id)
    except HTTPException as error:
        if error.status_code != 429:
            raise
        return None  # Keep the exact plan in session evidence for admission retry.


def lookahead(db, settings, session):
    """Maintain only the three-block lead explicitly requested by the learner."""
    curriculum = db.get(Curriculum, session.curriculum_id)
    lesson = db.get(Lesson, curriculum.lesson_id)
    if lesson.course_id or session.state in {'complete', 'complete_with_support'}:
        return None
    queued = enqueue_initial_window(db, settings, curriculum, lesson, consumer=session.id)
    objectives = curriculum.blueprint['objectives']
    current = next((i for i, x in enumerate(objectives) if x['id'] == session.objective_id), 0)
    for index, objective in enumerate(objectives):
        target = index + LEAD
        if target >= len(objectives):
            break
        if target < current or (target == current and session.selected_block_id):
            continue
        if session.evidence.get(objective['id'], {}).get('attempts'):
            job = adapt_ahead(db, settings, session, objective['id'])
            if job:
                queued.append(job)
    return queued[0] if queued else None


def adaptive_view(db, session, curriculum):
    lesson = db.get(Lesson, curriculum.lesson_id)
    pending = []
    current = next((i for i, item in enumerate(curriculum.blueprint['objectives']) if item['id'] == session.objective_id), 0)
    for index, objective in enumerate(curriculum.blueprint['objectives']):
        plan = session.evidence.get(objective['id'], {}).get('adaptive_plan')
        if plan and index >= current:
            pending.append({'objective_id': objective['id'], 'title': objective['title'], 'number': index + 1,
                            'level': plan['adaptation']['level'],
                            'based_on_assessment': plan['adaptation']['assessment_number']})
    selected = db.get(Block, session.selected_block_id) if session.selected_block_id else None
    return {'mode': 'reviewed_classroom' if lesson.course_id else 'rolling', 'lead_blocks': LEAD,
            'total_blocks': len(curriculum.blueprint['objectives']),
            'understanding': understanding(session.evidence, curriculum.blueprint['objectives']),
            'current_teaching': selected.verification.get('adaptation') if selected else None,
            'planned': pending}
