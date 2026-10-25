"""Platform integration fixtures; these do not establish live provider acceptance."""
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.auth import Actor
from server.database import (Assessment, Asset, Base, Block, Course, Curriculum, Job,
    Attempt, LearningSession, Lesson, Membership, Profile, Source, SourceVersion, StageResult, make_engine, session_factory)
from server.lessons.contracts import CurriculumPlan, digest
from server.platform import create_app
from server.platform_settings import PlatformSettings
from server.worker.queue import JobContext, claim, enqueue


@pytest.fixture
def platform():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    identities = {name: str(uuid4()) for name in ("alice", "bob", "teacher", "admin")}
    def verify(token):
        if token not in identities:
            raise HTTPException(401, "Invalid test token")
        return Actor(identities[token], token + "@example.test", token.title())
    class Objects:
        def sign(self, key):
            return "https://private-storage.example.test/" + key
    app = create_app(PlatformSettings(), engine=engine, verify_token=verify, objects=Objects())
    with factory.begin() as db:
        for name, identifier in identities.items():
            db.add(Profile(id=identifier, email=name + "@example.test", display_name=name,
                           privilege="teacher" if name == "teacher" else "administrator" if name == "admin" else "student"))
    with TestClient(app) as client:
        yield client, factory, identities


def headers(name):
    return {"Authorization": "Bearer " + name}


def seed_lesson(factory, ids, *, owner="alice", course_id=None, count=2):
    with factory.begin() as db:
        lesson = Lesson(owner_id=ids[owner], course_id=course_id, title="Fixture Python lesson")
        db.add(lesson)
        db.flush()
        objectives = [{"id": f"o{i}", "title": f"Objective {i}", "description": "Explain a complete fixture concept",
                       "prerequisites": [f"o{i-1}"] if i else [], "evidence": [], "worked_example": "An explicit worked example", "visual_approach": "A readable trace"} for i in range(count)]
        curriculum = Curriculum(lesson_id=lesson.id, blueprint={"objectives": objectives}, confirmed=True, availability="ready")
        db.add(curriculum)
        db.flush()
        for obj in objectives:
            for profile in ("normal", "recap"):
                block = Block(curriculum_id=curriculum.id, objective_id=obj["id"], profile=profile, state="ready",
                              script={"scenes": [{"title": "Fixture scene"}]}, verification={"accepted": True}, checksum="f" * 64)
                db.add(block)
                db.flush()
                for kind in ("clip", "caption"):
                    db.add(Asset(block_id=block.id, position=0, kind=kind, object_key=f"private/{block.id}/{kind}", checksum="f" * 64,
                                 duration=10, mime="video/mp4" if kind == "clip" else "text/vtt", transcript="A fixture explanation."))
            for variant in ("base", "equivalent"):
                db.add(Assessment(curriculum_id=curriculum.id, objective_id=obj["id"], variant=variant,
                    public={"kind": "mcq", "prompt": "Which option is correct?", "options": [{"id": "yes", "text": "Correct fixture"}, {"id": "no", "text": "Incorrect fixture"}]},
                    private={"correct": ["yes"], "hints": ["Use the concept."], "explanation": "The worked fixture solution is correct.", "misconception_map": {"no": "boundary"}}, validated=True))
        return lesson.id, curriculum.id


def start(client, curriculum, name="alice", assignment_id=None):
    response = client.post("/api/sessions", json={"curriculum_id": curriculum, "assignment_id": assignment_id}, headers=headers(name))
    assert response.status_code == 201, response.text
    return response.json()


def finish_clip(client, session, name="alice"):
    response = client.patch(f"/api/sessions/{session['id']}/progress", headers=headers(name), json={
        "expected_revision": session["revision"], "route_revision": session["route_revision"], "block_id": session["selected_block_id"],
        "clip": session["position"]["clip"], "offset": 10, "ended": True})
    assert response.status_code == 200, response.text
    return response.json()


def answer_body(session, choice="yes"):
    return {"session_id": session["id"], "assessment_id": session["question"]["id"],
            "route_revision": session["route_revision"], "expected_revision": session["revision"],
            "idempotency_key": uuid4().hex, "answer": {"choice": choice}}


def test_setup_starts_and_reports_missing_services(platform):
    client, _, _ = platform
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/ready").status_code == 503
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/session").status_code == 404
    assert "database" in client.get("/api/config").json()["setup_required"]


def test_student_cannot_promote_self_or_create_course(platform):
    client, _, ids = platform
    assert client.post("/api/courses", headers=headers("alice"), json={"title": "Course"}).status_code == 403
    assert client.post(f"/api/admin/users/{ids['alice']}/privilege?value=teacher", headers=headers("alice")).status_code == 403
    assert client.post("/api/courses", headers=headers("teacher"), json={"title": "Course", "role": "administrator"}).status_code == 422


def test_enrollment_revocation_and_teacher_independent_isolation(platform):
    client, factory, ids = platform
    course = client.post("/api/courses", headers=headers("teacher"), json={"title": "Python class"}).json()
    code = client.post(f"/api/courses/{course['id']}/enrollment-code", headers=headers("teacher")).json()["code"]
    assert client.post("/api/courses/join", headers=headers("alice"), json={"code": code}).status_code == 200
    _, curriculum = seed_lesson(factory, ids)
    assert client.get(f"/api/lessons/versions/{curriculum}", headers=headers("teacher")).status_code == 404
    members = client.get(f"/api/courses/{course['id']}/members", headers=headers("teacher")).json()
    assert client.patch(f"/api/courses/{course['id']}/members/{members[0]['id']}?active=false", headers=headers("teacher")).status_code == 200
    assert client.post("/api/courses/join", headers=headers("alice"), json={"code": code}).status_code == 403
    client.delete(f"/api/courses/{course['id']}/enrollment-code", headers=headers("teacher"))
    assert client.post("/api/courses/join", headers=headers("bob"), json={"code": code}).status_code == 404


def test_source_correction_is_versioned_and_private(platform):
    client, _, _ = platform
    source = client.post("/api/sources", headers=headers("alice"), json={"kind": "text", "title": "Source notes", "text": "Python loops repeat a block of code.\n\n    for n in range(3):\n        print(n)"}).json()
    assert source["state"] == "needs_confirmation"
    assert "        print(n)" in source["evidence"][0]["text"]
    assert client.get(f"/api/sources/{source['id']}", headers=headers("bob")).status_code == 404
    body = {"expected_version": 1, "evidence": source["evidence"], "confirm": True, "note": "Checked the original notes"}
    response = client.put(f"/api/sources/{source['id']}/preview", headers=headers("alice"), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert client.put(f"/api/sources/{source['id']}/preview", headers=headers("alice"), json=body).status_code == 409


def test_uncertain_source_cannot_be_confirmed(platform):
    client, _, _ = platform
    source = client.post("/api/sources", headers=headers("alice"), json={"kind": "text", "title": "Uncertain notes", "text": "An unclear source block"}).json()
    source["evidence"][0]["uncertainty"] = ["unclear number"]
    assert client.put(f"/api/sources/{source['id']}/preview", headers=headers("alice"), json={"expected_version": 1,
        "evidence": source["evidence"], "confirm": True, "note": "Cannot read the number"}).status_code == 409


def test_complete_multiobjective_journey_and_no_answer_key_leak(platform):
    client, factory, ids = platform
    _, curriculum = seed_lesson(factory, ids, count=5)
    session = start(client, curriculum)
    assert session["question"] is None
    assert "correct" not in str(client.get(f"/api/lessons/versions/{curriculum}", headers=headers("alice")).json())
    for index in range(5):
        assert session["objective_id"] == f"o{index}"
        session = finish_clip(client, session)
        assert "private" not in session["question"] and "correct" not in session["question"]
        response = client.post("/api/attempts", headers=headers("alice"), json=answer_body(session))
        assert response.status_code == 202, response.text
        assert response.json()["result"]["passed"]
        session = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert session["state"] == "complete"
    assert len(session["evidence"]) == 5
    assert all(x["status"] == "passed" and x["viewed"] for x in session["evidence"].values())


def test_duplicate_submission_is_one_grade_and_stale_progress_is_rejected(platform):
    client, factory, ids = platform
    _, curriculum = seed_lesson(factory, ids)
    initial = start(client, curriculum)
    session = finish_clip(client, initial)
    body = answer_body(session)
    first = client.post("/api/attempts", headers=headers("alice"), json=body).json()
    second = client.post("/api/attempts", headers=headers("alice"), json=body).json()
    assert first == second
    body["answer"] = {"choice": "no"}
    assert client.post("/api/attempts", headers=headers("alice"), json=body).status_code == 409
    response = client.patch(f"/api/sessions/{session['id']}/progress", headers=headers("alice"), json={
        "expected_revision": initial["revision"], "route_revision": initial["route_revision"], "block_id": initial["selected_block_id"], "clip": 0, "offset": 1})
    assert response.status_code == 409
    assert client.get(f"/api/sessions/{session['id']}", headers=headers("bob")).status_code == 404


def test_recap_equivalent_and_solution_do_not_fabricate_mastery(platform):
    client, factory, ids = platform
    _, curriculum = seed_lesson(factory, ids, count=1)
    session = start(client, curriculum)
    for _ in range(3):
        session = finish_clip(client, session)
        response = client.post("/api/attempts", headers=headers("alice"), json=answer_body(session, "no"))
        assert response.status_code == 202, response.text
        session = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert session["state"] == "needs_revision"
    assert session["evidence"]["o0"]["status"] == "unresolved"
    assert response.json()["result"]["worked_solution"]
    session = client.post(f"/api/sessions/{session['id']}/revision-route", headers=headers("alice"), json={"expected_revision": session["revision"]}).json()
    session = finish_clip(client, session)
    client.post("/api/attempts", headers=headers("alice"), json=answer_body(session))
    session = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert session["state"] == "complete_with_support"
    assert session["evidence"]["o0"]["status"] == "assisted"


def test_optional_prerequisite_review_rejoins_without_regrading_passed_objective(platform):
    client, factory, ids = platform
    _, curriculum = seed_lesson(factory, ids, count=2)
    session = finish_clip(client, start(client, curriculum))
    client.post("/api/attempts", headers=headers("alice"), json=answer_body(session))
    session = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    for _ in range(3):
        session = finish_clip(client, session)
        client.post("/api/attempts", headers=headers("alice"), json=answer_body(session, "no"))
        session = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert session["state"] == "needs_revision" and session["objective_id"] == "o1"
    response = client.post(f"/api/sessions/{session['id']}/revision-route", headers=headers("alice"), json={"expected_revision": session["revision"], "prerequisite_id": "o0"})
    assert response.status_code == 200, response.text
    review = response.json()
    assert review["position"]["reviewing_prerequisite"] == "o0" and review["objective_id"] == "o1"
    rejoined = finish_clip(client, review)
    assert rejoined["state"] == "playing" and "reviewing_prerequisite" not in rejoined["position"]
    assert rejoined["selected_block_id"] != review["selected_block_id"] and rejoined["route_revision"] > review["route_revision"]
    assert rejoined["evidence"]["o0"]["status"] == "passed" and rejoined["evidence"]["o0"]["attempts"] == 1
    checkpoint = finish_clip(client, rejoined)
    assert checkpoint["objective_id"] == "o1"
    with factory.begin() as db:
        assert db.get(Assessment, checkpoint["question"]["id"]).variant == "equivalent"


def test_classroom_requires_exact_review_and_revocation_blocks_assets(platform):
    client, factory, ids = platform
    course = client.post("/api/courses", headers=headers("teacher"), json={"title": "Python classroom"}).json()
    _, curriculum = seed_lesson(factory, ids, owner="teacher", course_id=course["id"])
    assert client.post(f"/api/reviews/{curriculum}/publish", headers=headers("teacher")).status_code == 409
    review = client.get(f"/api/reviews/{curriculum}", headers=headers("teacher")).json()
    body = {"expected_fingerprint": review["fingerprint"], "coverage": True, "factual": True, "assessments": True, "media": True}
    assert client.post(f"/api/reviews/{curriculum}/approve", headers=headers("teacher"), json={**body, "expected_fingerprint": "0" * 64}).status_code == 409
    assert client.post(f"/api/reviews/{curriculum}/approve", headers=headers("teacher"), json=body).status_code == 200
    assert client.post(f"/api/reviews/{curriculum}/publish", headers=headers("teacher")).status_code == 200
    assignment = client.post(f"/api/courses/{course['id']}/assignments", headers=headers("teacher"), json={"curriculum_id": curriculum}).json()
    code = client.post(f"/api/courses/{course['id']}/enrollment-code", headers=headers("teacher")).json()["code"]
    client.post("/api/courses/join", headers=headers("alice"), json={"code": code})
    session = start(client, curriculum, assignment_id=assignment["id"])
    clip_id = session["clips"][0]["id"]
    assert client.get(f"/api/assets/{clip_id}/access?session_id={session['id']}", headers=headers("alice")).status_code == 200
    assert client.get(f"/api/reviews/{curriculum}", headers=headers("alice")).status_code == 404
    assert client.get(f"/api/assets/{clip_id}/access", headers=headers("bob")).status_code == 404
    client.post(f"/api/reviews/{curriculum}/unpublish", headers=headers("teacher"))
    assert client.get(f"/api/assets/{clip_id}/access?session_id={session['id']}", headers=headers("alice")).status_code == 403


def test_lease_recovery_cancellation_and_scoped_dedup(platform):
    _, factory, ids = platform
    settings = PlatformSettings()
    with factory.begin() as db:
        a = enqueue(db, settings, ids["alice"], "block", {"fixture": 1}, scope="private:alice")
        same = enqueue(db, settings, ids["alice"], "block", {"fixture": 1}, scope="private:alice")
        b = enqueue(db, settings, ids["bob"], "block", {"fixture": 1}, scope="private:bob")
        assert a.id == same.id and a.id != b.id
        identifier = a.id
    first = claim(factory)
    context = JobContext(factory, first)
    context.save("stage", {"x": 1}, {"accepted": True})
    with factory.begin() as db:
        db.get(Job, first["id"]).lease_until = time.time() - 1
    recovered = claim(factory)
    assert recovered["fence"] == first["fence"] + 1
    from server.providers.base import GenerationError
    with pytest.raises(GenerationError, match="recovered"):
        context.finish({"stale": True})
    latest = JobContext(factory, recovered)
    assert latest.saved("stage", {"x": 1}) == {"accepted": True}
    latest.finish({"done": True})


def test_cross_origin_mutation_rejected(platform):
    client, _, _ = platform
    response = client.post("/api/courses", headers={**headers("teacher"), "Origin": "https://evil.example"}, json={"title": "No course"})
    assert response.status_code == 403


def python_checkpoint(client, factory, ids):
    _, curriculum = seed_lesson(factory, ids, count=1)
    with factory.begin() as db:
        for question in db.scalars(select(Assessment).where(Assessment.curriculum_id == curriculum)):
            question.public = {"kind": "python", "prompt": "Print the integer two.", "starter_code": "print(2)"}
            question.private = {"tests": [{"stdin": "", "expected": "2", "essential": True, "weight": 1, "category": "basic"}], "hints": ["Use print"], "explanation": "Printing two is the worked example."}
    client.app.state.runner.ready = lambda: None
    return finish_clip(client, start(client, curriculum))


def test_code_draft_is_revision_checked_and_restored_from_account(platform):
    client, factory, ids = platform
    session = python_checkpoint(client, factory, ids)
    body = {"expected_revision": session["revision"], "route_revision": session["route_revision"], "assessment_id": session["question"]["id"], "code": "# preserve indentation\n    print(2)\n"}
    url = f"/api/sessions/{session['id']}/draft"
    response = client.patch(url, headers=headers("alice"), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["position"]["code_draft"] == body["code"]
    assert response.json()["revision"] > session["revision"]
    assert client.patch(url, headers=headers("alice"), json=body).status_code == 409
    assert client.patch(url, headers=headers("bob"), json=body).status_code == 404
    assert client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()["position"]["code_draft"] == body["code"]


def test_cancelled_grading_preserves_attempt_and_can_resume_after_refresh(platform):
    client, factory, ids = platform
    session = python_checkpoint(client, factory, ids)
    body = answer_body(session)
    body["answer"] = {"code": "print(2)"}
    submitted = client.post("/api/attempts", headers=headers("alice"), json=body).json()
    with factory.begin() as db:
        job_id = db.scalar(select(Job.id).where(Job.kind == "grade"))
        db.add(StageResult(job_id=job_id, stage="runner_tokens", input_hash=digest({"fixture": "failed-token"}), output={"tokens": ["permanently-failed-provider-token"]}))
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=headers("alice")).status_code == 200
    restored = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert restored["state"] == "checkpoint" and restored["position"]["code_draft"] == "print(2)"
    assert restored["last_attempt"]["state"] == "service_failed"
    assert restored["evidence"]["o0"].get("attempts", 0) == 0
    assert client.post(f"/api/attempts/{submitted['id']}/retry", headers=headers("alice")).status_code == 202
    with factory.begin() as db:
        assert db.scalar(select(StageResult).where(StageResult.job_id == job_id, StageResult.stage == "runner_tokens")) is None
    restored = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert restored["active_attempt_id"] == submitted["id"] and restored["state"] == "submitting"


def test_grading_claims_cannot_be_blocked_by_generation_jobs(platform):
    _, factory, ids = platform
    with factory.begin() as db:
        generation = enqueue(db, PlatformSettings(), ids["alice"], "block", {"test": "bulk"}, scope="private:alice")
        grading = enqueue(db, PlatformSettings(), ids["alice"], "grade", {"test": "submission"}, scope="private:alice", priority=0)
        gen_id, grade_id = generation.id, grading.id
    assert claim(factory, queue="generation")["id"] == gen_id
    assert claim(factory, queue="grading")["id"] == grade_id


def test_verification_claim_is_limited_to_its_disposable_owner(platform):
    _, factory, ids = platform
    with factory.begin() as db:
        enqueue(db, PlatformSettings(), ids["alice"], "block", {"test": "unrelated"}, scope="private:alice", priority=0)
        fixture = enqueue(db, PlatformSettings(), ids["bob"], "verification_fixture", {}, scope="verification:bob")
        identifier = fixture.id
    assert claim(factory, owner_id=ids["bob"])["id"] == identifier


def test_unverified_input_adapters_are_not_advertised_or_accepted(platform):
    client, _, _ = platform
    assert client.get("/api/config").json()["source_features"] == {"text": True, "topic": False, "document": False, "image": False, "youtube": False}
    assert client.post("/api/sources", headers=headers("alice"), json={"kind": "youtube", "title": "Video source", "text": "https://youtu.be/abcdefghijk"}).status_code == 503
    assert client.post("/api/sources/upload", headers=headers("alice"), files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 503


def test_source_cannot_reference_another_private_object(platform):
    client, _, _ = platform
    source = client.post("/api/sources", headers=headers("alice"), json={"kind": "text", "title": "Private notes", "text": "A source used for this specific lesson"}).json()
    source["evidence"][0]["image_key"] = "sources/bob/private/image.png"
    response = client.put(f"/api/sources/{source['id']}/preview", headers=headers("alice"), json={"expected_version": 1, "evidence": source["evidence"], "confirm": True, "note": "An invalid cross-user image reference"})
    assert response.status_code == 422


def test_issue_report_is_scoped_to_an_accessible_lesson(platform):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=1)
    body = {"curriculum_id": version, "category": "assessment", "description": "Please check this checkpoint wording against the supplied example."}
    assert client.post("/api/issues", headers=headers("bob"), json=body).status_code == 404
    assert client.post("/api/issues", headers=headers("alice"), json=body).status_code == 201


def test_queue_full_preserves_grade_and_selected_continuation_can_retry(platform):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=2)
    session = finish_clip(client, start(client, version))
    client.app.state.settings.max_jobs_per_user = 1
    with factory.begin() as db:
        for block in db.scalars(select(Block).where(Block.curriculum_id == version, Block.objective_id == "o1")):
            block.state = "planned"
        unrelated = enqueue(db, client.app.state.settings, ids["alice"], "source", {"fixture": "occupied"}, scope="private:alice")
        occupied_id = unrelated.id
    graded = client.post("/api/attempts", headers=headers("alice"), json=answer_body(session))
    assert graded.status_code == 202 and graded.json()["result"]["passed"]
    blocked = client.get(f"/api/sessions/{session['id']}", headers=headers("alice")).json()
    assert blocked["state"] == "recoverable_error" and blocked["objective_id"] == "o1"
    assert blocked["evidence"]["o0"]["status"] == "passed"
    assert blocked["position"]["wait_reason"] == "preparation_queue_full"
    client.post(f"/api/jobs/{occupied_id}/cancel", headers=headers("alice"))
    resumed = client.post(f"/api/sessions/{session['id']}/resume-continuation", headers=headers("alice"), json={"expected_revision": blocked["revision"]})
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["state"] == "waiting_for_block" and resumed.json()["continuation_job_id"]
    assert resumed.json()["evidence"]["o0"]["status"] == "passed"


def test_retry_cannot_bypass_queue_admission(platform):
    client, factory, ids = platform
    client.app.state.settings.max_jobs_per_user = 1
    with factory.begin() as db:
        stopped = Job(owner_id=ids["alice"], dedup_key=uuid4().hex * 2, kind="source", payload={}, state="cancelled")
        db.add(stopped); db.flush(); identifier = stopped.id
        enqueue(db, client.app.state.settings, ids["alice"], "source", {"fixture": "occupied"}, scope="private:alice")
    assert client.post(f"/api/jobs/{identifier}/retry", headers=headers("alice")).status_code == 429
    with factory.begin() as db:
        assert db.get(Job, identifier).state == "cancelled"
