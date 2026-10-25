"""Local fault and immutability fixtures; not live content acceptance."""
from types import SimpleNamespace

import pytest

from sqlalchemy import select

from server.database import Assessment, Block, Curriculum, Job
from server.lessons.contracts import BlockDraft, Verification, digest
from server.worker.queue import JobContext, claim, enqueue
from server.worker.tasks import prepare_block
from server.lessons.authoring import StructuredAuthor
from server.providers.base import GenerationError
from test_platform import platform, headers, seed_lesson, start


def draft_for(objective_id="o0", profile="normal"):
    return BlockDraft(objective_id=objective_id, profile=profile,
        explanation="This is a deliberately hand-authored recovery fixture, not release content.",
        worked_example="Input travels from a first step to a second step.",
        source_refs=[{"source_version_id": "fixture-version", "block_id": "fixture-evidence"}],
        scenes=[{"id": "s1", "title": "Fixture process", "bullets": ["Fixture only"],
                 "utterances": [{"text": "Follow the process from start to finish.", "visual_step": 0}],
                 "visual": {"kind": "process", "caption": "A hand-authored integration fixture", "nodes": [{"id": "a", "label": "Start"}, {"id": "b", "label": "Finish"}], "edges": [{"source": "a", "target": "b"}]}}])


def test_manual_edit_prepares_support_without_reusing_its_revision(platform, monkeypatch, tmp_path):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=1)
    draft = draft_for()
    with factory.begin() as db:
        normal = db.scalar(select(Block).where(Block.curriculum_id == version, Block.profile == "normal"))
        normal.script, normal.verification = draft.model_dump(), {"manual_edit": True}
        # The seeded fixture assets are replaced by an authored edit, as in the API.
        normal.state = "planned"
        objective = {"id": "o0", "title": "Fixture concept", "description": "An intentionally controlled fixture concept", "prerequisites": [], "evidence": [{"source_version_id": "fixture-version", "block_id": "fixture-evidence"}], "worked_example": "A fixed example", "visual_approach": "A process"}
        db.get(Curriculum, version).blueprint = {"title": "Fixture curriculum", "scope": "Controlled fixture scope", "prerequisites": [], "notation": {}, "objectives": [objective]}
        payload = {"curriculum_id": version, "objective_id": "o0", "profile": "normal", "context_hash": "base", "misconception": None, "manual_revision": digest(normal.script)}
        enqueue(db, client.app.state.settings, ids["alice"], "block", payload, scope="fixture:manual")
    verification = Verification(findings=[], evidence_checked=True, objective_covered=True, example_consistent=True)
    class Author:
        def __init__(self, *args): pass
        def ask(self, *args, **kwargs): return verification
    monkeypatch.setattr("server.worker.tasks.StructuredAuthor", Author)
    monkeypatch.setattr("server.worker.tasks.objective_packets", lambda *args: [{"id": "fixture-version", "evidence": [{"id": "fixture-evidence", "text": "Trusted test data"}]}])
    monkeypatch.setattr("server.lessons.production.produce_block", lambda *args: [])
    context = JobContext(factory, claim(factory))
    result = prepare_block(context, client.app.state.settings, None, None, payload, tmp_path)
    assert result["curriculum_id"] == version
    with factory.begin() as db:
        assert all(x.state == "ready" for x in db.scalars(select(Block).where(Block.curriculum_id == version)))


def test_draft_assessment_edit_validates_and_requires_fork_after_session(platform):
    client, factory, ids = platform
    _, version = seed_lesson(factory, ids, count=1)
    packet = client.get(f"/api/reviews/{version}", headers=headers("alice")).json()
    question = packet["assessments"][0]
    definition = {k: question[k] for k in ("objective_id", "variant")}
    definition.update(question=question["question"], key=question["key"])
    definition["question"]["prompt"] = "Choose the correct hand-authored fixture option."
    url = f"/api/lessons/versions/{version}/assessments/{question['id']}"
    response = client.patch(url, headers=headers("alice"), json={"expected_fingerprint": packet["fingerprint"], "definition": definition})
    assert response.status_code == 202, response.text
    with factory.begin() as db:
        assert not db.get(Assessment, question["id"]).validated
        db.get(Assessment, question["id"]).validated = True
    start(client, version)
    packet = client.get(f"/api/reviews/{version}", headers=headers("alice")).json()
    assert client.patch(url, headers=headers("alice"), json={"expected_fingerprint": packet["fingerprint"], "definition": definition}).status_code == 409
    fork = client.post(f"/api/lessons/versions/{version}/fork", headers=headers("alice"), json={})
    assert fork.status_code == 201 and fork.json()["curriculum_id"] != version


def test_chunked_oversize_request_is_rejected(platform):
    client, _, _ = platform
    def chunks():
        yield b'{"title":"Large notes","kind":"text","text":"'
        for _ in range(34): yield b"a" * 65536
        yield b'"}'
    response = client.post("/api/sources", headers={**headers("alice"), "Content-Type": "application/json"}, content=chunks())
    assert response.status_code == 413, response.text


@pytest.mark.parametrize("recover", [True, False])
def test_schema_failures_share_the_bounded_author_repair_budget(recover):
    class Author(StructuredAuthor):
        def __init__(self):
            super().__init__(SimpleNamespace(text_model="fixture-author", verifier_model="fixture-verifier"), None)
            self.author_calls = 0
        def ask(self, stage, *args, **kwargs):
            if stage.startswith("author_"):
                self.author_calls += 1
                assert kwargs["repairs"] == 0
                if not recover or self.author_calls < 3:
                    raise GenerationError("CONTENT_NEEDS_REVIEW", "Fixture schema failure")
                return draft_for()
            return Verification(findings=[], evidence_checked=True, objective_covered=True, example_consistent=True)
    author = Author()
    objective = {"id": "o0", "prerequisites": [], "evidence": [{"source_version_id": "fixture-version", "block_id": "fixture-evidence"}]}
    blueprint = {"title": "Fixture curriculum", "scope": "Controlled recovery fixture", "prerequisites": [], "notation": {}, "objectives": [objective]}
    if recover:
        draft, review = author.author(blueprint, objective, [], "normal", None)
        assert draft.objective_id == "o0" and review.accepted()
    else:
        with pytest.raises(GenerationError, match="two repairs"): author.author(blueprint, objective, [], "normal", None)
    assert author.author_calls == 3
