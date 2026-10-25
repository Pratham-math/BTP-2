"""Persisted preparation stages. All long work happens outside DB transactions."""
import json
import os
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from server.config import PROJECT_DIR
from server.database import (Assessment, Asset, Attempt, Block, Curriculum, Job,
    LearningSession, Lesson, Source, SourceVersion)
from server.ingestion.readers import text_blocks
from server.lessons.authoring import StructuredAuthor
from server.lessons.contracts import BlockDraft, CurriculumPlan, GradingKey, Verification, digest
from server.providers.base import GenerationError
from server.runtime import run_command


def source_packets(db, ids):
    packets = []
    for identifier in ids:
        source = db.get(SourceVersion, identifier)
        if not source or not source.confirmed:
            raise GenerationError("SOURCE_NEEDS_CONFIRMATION", "Confirm every source version before generation.")
        packets.append({"id": source.id, "evidence": source.evidence})
    return packets


def objective_packets(db, objective):
    by_source = {}
    for ref in objective["evidence"]:
        by_source.setdefault(ref["source_version_id"], set()).add(ref["block_id"])
    packets = source_packets(db, list(by_source))
    for packet in packets:
        packet["evidence"] = [x for x in packet["evidence"] if x["id"] in by_source[packet["id"]]]
        if len(packet["evidence"]) != len(by_source[packet["id"]]):
            raise GenerationError("INVALID_EVIDENCE", "A referenced source block is missing.")
    return packets


def wait_runner(runner, tokens, key, context):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        context.check()
        result = runner.poll(tokens, key)
        if result is not None:
            return result
        time.sleep(1)
    raise GenerationError("RUNNER_TIMEOUT", "The grading service did not finish in time. Retry the saved submission.")


def validate_questions(plan, packets, author, runner, context):
    from server.lessons.planning import evidence_for, focused_blueprint
    blueprint = plan.public_blueprint()
    objectives = {x['id']: x for x in blueprint['objectives']}
    for number, assessment in enumerate(plan.assessments):
        key, question = assessment.key.model_dump(), assessment.question.model_dump()
        objective = objectives[assessment.objective_id]
        relevant = evidence_for(packets, objective)
        inputs = {"question": question, "key": key, "evidence": relevant, "verifier": author.settings.verifier_model}
        if context.saved(f"assessment_valid_{number}", inputs):
            continue
        verification = author.ask(f"assessment_verify_{number}", author.settings.verifier_model, Verification,
            "Verify this assessment and private key against the ORIGINAL evidence. Check solvability, exact key correctness, "
            "essential tests, hidden edge cases, reference outputs, misconceptions, hints and whether the lesson can teach the task. "
            "Return critical findings for incorrect or ambiguous keys. Do not accept unsourced content.",
            {"assessment": assessment.model_dump(), "original_evidence": relevant, "fixed_curriculum": focused_blueprint(blueprint, objective)})
        if not verification.accepted():
            raise GenerationError("ASSESSMENT_NEEDS_REVIEW", "An assessment or its key has unresolved verification findings.")
        if question["kind"] == "python":
            if not key["alternative_solution"] or len(key["known_wrong_solutions"]) < 2:
                raise GenerationError("ASSESSMENT_NEEDS_REVIEW", "Python validation requires alternative correct code and at least two known wrong solutions.")
            for index, code in enumerate([key["reference_solution"], key["alternative_solution"], *key["known_wrong_solutions"]]):
                run_inputs = {"code": code, "key": key}
                saved = context.saved(f"reference_{number}_{index}", run_inputs)
                tokens = saved.get("tokens") if saved else None
                if not tokens:
                    tokens = runner.submit(code, key)
                    context.save(f"reference_{number}_{index}", run_inputs, {"tokens": tokens})
                result = wait_runner(runner, tokens, key, context)
                if result["passed"] != (index < 2):
                    raise GenerationError("ASSESSMENT_NEEDS_REVIEW", "The Python test set failed a reference or accepted a known incorrect solution.")
        context.save(f"assessment_valid_{number}", inputs, {"accepted": True, "verification": verification.model_dump()})


def prepare_curriculum(context, settings, objects, runner, payload, folder):
    with context.transaction() as (db, job):
        lesson = db.get(Lesson, payload["lesson_id"])
        if not lesson or lesson.retired or lesson.owner_id != job.owner_id:
            raise GenerationError("SCOPE_CHANGED", "The lesson is no longer available for preparation.")
        packets = source_packets(db, payload["source_version_ids"])
    author = StructuredAuthor(settings, context)
    plan = author.plan(packets, payload["goal"])
    # Plan is saved and resumable even if runner/model validation remains blocked.
    validate_questions(plan, packets, author, runner, context)
    with context.transaction() as (db, job):
        existing = db.scalar(select(Curriculum).where(Curriculum.lesson_id == payload["lesson_id"]).limit(1))
        if existing:
            return {"curriculum_id": existing.id}
        curriculum = Curriculum(lesson_id=payload["lesson_id"], blueprint=plan.public_blueprint())
        db.add(curriculum)
        db.flush()
        for assessment in plan.assessments:
            db.add(Assessment(curriculum_id=curriculum.id, objective_id=assessment.objective_id, variant=assessment.variant,
                              public=assessment.question.model_dump(), private=assessment.key.model_dump(), validated=True))
        for objective in plan.objectives:
            for profile in ("normal", "recap"):
                db.add(Block(curriculum_id=curriculum.id, objective_id=objective.id, profile=profile, context_hash="base"))
        return {"curriculum_id": curriculum.id}


def prepare_block(context, settings, objects, runner, payload, folder, *, include_support=True):
    from server.lessons.production import produce_block
    with context.transaction() as (db, job):
        curriculum = db.scalar(select(Curriculum).where(Curriculum.id == payload["curriculum_id"]).with_for_update())
        lesson = db.get(Lesson, curriculum.lesson_id) if curriculum else None
        if not curriculum or not curriculum.confirmed or not lesson or lesson.retired or curriculum.publication != "draft":
            raise GenerationError("IMMUTABLE_VERSION", "Preparation requires a confirmed, active draft lesson version.")
        objective = next((x for x in curriculum.blueprint["objectives"] if x["id"] == payload["objective_id"]), None)
        if not objective:
            raise GenerationError("INVALID_OBJECTIVE", "The selected objective is not in the fixed curriculum.")
        packets = objective_packets(db, objective)
        blueprint = curriculum.blueprint
        block = db.scalar(select(Block).where(Block.curriculum_id == curriculum.id, Block.objective_id == objective["id"],
            Block.profile == payload["profile"], Block.context_hash == payload["context_hash"]))
        if block is None:
            block = Block(curriculum_id=curriculum.id, objective_id=objective["id"], profile=payload["profile"], context_hash=payload["context_hash"])
            db.add(block)
            db.flush()
        block_id, already_ready = block.id, block.state == "ready"
        manual_script = block.script if block.verification.get("manual_edit") else None
        original_script_hash = digest(block.script)
        if payload.get("manual_revision") and digest(block.script) != payload["manual_revision"]:
            raise GenerationError("DRAFT_CHANGED", "The manual edit changed before this preparation began.")
        if not already_ready:
            block.state = "authoring"
    if not already_ready:
        author = StructuredAuthor(settings, context)
        if manual_script:
            from server.lessons.planning import focused_blueprint
            draft = BlockDraft.model_validate(manual_script)
            verification = author.ask("verify_manual", settings.verifier_model, Verification,
                "Verify this author-edited block against the original evidence, fixed objective and curriculum. Flag critical factual, source, example, visual and coverage errors. Do not alter the author's text.",
                {"draft": manual_script, "objective": objective, "original_evidence": packets, "curriculum": focused_blueprint(blueprint, objective)})
            if not verification.accepted():
                raise GenerationError("CONTENT_NEEDS_REVIEW", "The edited block retains critical verification findings.")
        else:
            draft, verification = author.author(blueprint, objective, packets, payload["profile"], payload.get("misconception"))
        from server.assessment.trace_validation import trace_harness, trace_key
        for scene in draft.scenes:
            if scene.visual.kind == "code_trace":
                harness, key = trace_harness(scene.visual), trace_key()
                inputs = {"visual": scene.visual.model_dump(), "runtime": settings.runner_language_id}
                checked = context.saved("example_trace_" + scene.id, inputs)
                if not checked or not checked.get("accepted"):
                    saved_run = context.saved("example_run_" + scene.id, inputs)
                    tokens = saved_run["tokens"] if saved_run else runner.submit(harness, key)
                    if not saved_run:
                        context.save("example_run_" + scene.id, inputs, {"tokens": tokens})
                    result = wait_runner(runner, tokens, key, context)
                    if not result["passed"]:
                        raise GenerationError("TRACE_NEEDS_REVIEW", "The pictured code states do not match execution in the isolated runner.")
                    context.save("example_trace_" + scene.id, inputs, {"accepted": True})
        with context.transaction() as (db, _):
            block = db.get(Block, block_id)
            if digest(block.script) != original_script_hash:
                raise GenerationError("DRAFT_CHANGED", "An author changed this block during generation. The edit was preserved.")
            block.script, block.verification, block.state = draft.model_dump(), {"accepted": True, "manual_edit": bool(manual_script), **verification.model_dump()}, "rendering"
        assets = produce_block(draft, folder / block_id, context, objects, f"lessons/{payload['curriculum_id']}/{block_id}")
        with context.transaction() as (db, _):
            curriculum = db.scalar(select(Curriculum).where(Curriculum.id == payload["curriculum_id"]).with_for_update())
            block = db.get(Block, block_id)
            # Recheck version publication before attaching any newly generated assets.
            if curriculum.publication != "draft":
                raise GenerationError("IMMUTABLE_VERSION", "This version changed during preparation. No new assets were attached.")
            if block.script != draft.model_dump():
                raise GenerationError("DRAFT_CHANGED", "This block was edited while rendering. No outdated assets were attached.")
            for asset in assets:
                existing = db.scalar(select(Asset).where(Asset.block_id == block.id, Asset.position == asset["position"], Asset.kind == asset["kind"]))
                if existing is None:
                    db.add(Asset(block_id=block.id, **asset))
            db.flush()  # Attach all assets while the block is still rendering.
            block.checksum, block.state = digest({"script": block.script, "assets": assets}), "ready"
            curriculum.manifest_revision += 1
    if include_support and payload["profile"] != "recap":
        support_payload = {k: v for k, v in payload.items() if k != "manual_revision"}
        prepare_block(context, settings, objects, runner, {**support_payload, "profile": "recap", "context_hash": "base", "misconception": None}, folder, include_support=False)
    with context.transaction() as (db, _):
        curriculum = db.get(Curriculum, payload["curriculum_id"])
        blocks = db.scalars(select(Block).where(Block.curriculum_id == curriculum.id, Block.context_hash == "base")).all()
        if all(x.state == "ready" for x in blocks) and len(blocks) == len(curriculum.blueprint["objectives"]) * 2:
            curriculum.availability = "ready"
        else:
            curriculum.availability = "playable_partial"
    return {"block_id": block_id, "curriculum_id": payload["curriculum_id"]}


def prepare_whole_lesson(context, settings, objects, runner, payload, folder):
    with context.transaction() as (db, _):
        curriculum = db.get(Curriculum, payload["curriculum_id"])
        if not curriculum:
            raise GenerationError("INVALID_LESSON", "Lesson not found.")
        ids = [x["id"] for x in curriculum.blueprint["objectives"]]
    for objective_id in ids:
        prepare_block(context, settings, objects, runner, {"curriculum_id": payload["curriculum_id"], "objective_id": objective_id,
            "profile": "normal", "context_hash": "base", "misconception": None}, folder)
    return {"curriculum_id": payload["curriculum_id"]}


def grade_attempt(context, settings, objects, runner, payload, folder):
    from server.learning.service import apply_grade
    with context.transaction() as (db, _):
        attempt = db.get(Attempt, payload["attempt_id"])
        if not attempt or attempt.state == "graded":
            return {"attempt_id": payload["attempt_id"]}
        assessment = db.get(Assessment, attempt.assessment_id)
        code, key = attempt.answer["code"], assessment.private
        attempt.state = "running"
    inputs = {"code": code, "key": key, "runtime": settings.runner_language_id}
    saved = context.saved("runner_tokens", inputs)
    tokens = saved["tokens"] if saved else runner.submit(code, key)
    if not saved:
        context.save("runner_tokens", inputs, {"tokens": tokens})
    result = wait_runner(runner, tokens, key, context)
    with context.transaction() as (db, _):
        attempt = db.get(Attempt, payload["attempt_id"])
        session = db.scalar(select(LearningSession).where(LearningSession.id == attempt.session_id).with_for_update())
        apply_grade(db, settings, session, attempt, result)
    return {"attempt_id": payload["attempt_id"]}


def validate_edited_assessment(context, settings, objects, runner, payload, folder):
    with context.transaction() as (db, _):
        target = db.get(Assessment, payload["assessment_id"])
        if not target:
            raise GenerationError("INVALID_ASSESSMENT", "Assessment not found.")
        curriculum = db.get(Curriculum, target.curriculum_id)
        if curriculum.publication != "draft":
            raise GenerationError("IMMUTABLE_VERSION", "Only draft assessment keys can be changed.")
        definitions = [{"objective_id": x.objective_id, "variant": x.variant, "question": x.public, "key": x.private}
                       for x in db.scalars(select(Assessment).where(Assessment.curriculum_id == curriculum.id))]
        plan = CurriculumPlan.model_validate({**curriculum.blueprint, "assessments": definitions})
        source_ids = sorted({ref["source_version_id"] for objective in curriculum.blueprint["objectives"] for ref in objective["evidence"]})
        packets = source_packets(db, source_ids)
    validate_questions(plan, packets, StructuredAuthor(settings, context), runner, context)
    with context.transaction() as (db, _):
        target = db.get(Assessment, payload["assessment_id"])
        definition = {"objective_id": target.objective_id, "variant": target.variant, "question": target.public, "key": target.private}
        if digest(definition) != payload["revision"]:
            raise GenerationError("DRAFT_CHANGED", "The assessment changed while its checks were running. The newer edit was preserved.")
        target.validated = True
    return {"assessment_id": payload["assessment_id"]}


def prepare_source(context, settings, objects, runner, payload, folder):
    with context.transaction() as (db, _):
        source = db.get(Source, payload["source_id"])
        if not source or source.state == "retired":
            raise GenerationError("SOURCE_UNAVAILABLE", "The source was deleted or is unavailable.")
        kind, metadata, object_key, owner_id = source.kind, source.metadata_json, source.object_key, source.owner_id
    warnings = []
    if kind == "topic":
        from server.ingestion.curated import fetch_topic_evidence
        evidence = fetch_topic_evidence(metadata["input"])
    elif kind == "youtube":
        from server.ingestion.vision import extract_vision
        StructuredAuthor(settings, context).quota()
        evidence, warnings = extract_vision(settings, youtube_url=metadata["input"])
    else:
        suffix = metadata["suffix"]
        local = folder / ("source" + suffix)
        objects.download(object_key, local, settings.max_upload_bytes)
        if kind == "image":
            from server.ingestion.vision import extract_vision
            StructuredAuthor(settings, context).quota()
            evidence, warnings = extract_vision(settings, path=local)
            for block in evidence:
                block["image_key"] = object_key
        elif kind in {"pdf", "pptx", "ppt"}:
            from server.ingestion.sandbox import extract_in_sandbox
            evidence, warnings = extract_in_sandbox(local, kind, objects=objects, prefix=f"sources/{owner_id}/{payload['source_id']}/previews")
        else:
            raise GenerationError("CONVERSION_NOT_CONFIGURED", "Legacy PPT needs a verified isolated conversion service. Export it as PPTX or PDF for now.")
    context.check()
    with context.transaction() as (db, _):
        source = db.scalar(select(Source).where(Source.id == payload["source_id"]).with_for_update())
        if source.state == "retired":
            raise GenerationError("SOURCE_UNAVAILABLE", "The source was deleted during extraction.")
        # A repeated at-least-once extraction must not overwrite a corrected preview.
        if source.current_version:
            return {"source_id": source.id}
        source.current_version += 1
        source.metadata_json = {**source.metadata_json, 'preview_keys': sorted({x['image_key'] for x in evidence if x.get('image_key')})}
        db.add(SourceVersion(source_id=source.id, number=source.current_version, evidence=evidence, warnings=warnings, content_hash=digest(evidence)))
        source.state = "needs_confirmation"
    return {"source_id": payload["source_id"]}


from server.erasure import erase_account

HANDLERS = {"erase_account": erase_account, "source": prepare_source, "curriculum": prepare_curriculum, "block": prepare_block,
            "prepare_lesson": prepare_whole_lesson, "grade": grade_attempt, "validate_assessment": validate_edited_assessment}
