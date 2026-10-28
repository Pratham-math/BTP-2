"""Local-profile adapters and the three-block adaptive lead."""
import pytest
from sqlalchemy import select

from server.database import Job
from server.lessons.contracts import PlannedAssessment
from server.local_services import LocalObjectStore, LocalRunner, check_password, hash_password
from server.visuals import VisualSpec
from server.platform_settings import PlatformSettings
from tests.test_platform import answer_body, finish_clip, headers, platform, seed_lesson, start  # noqa: F401


def demo_runner():
    return LocalRunner(PlatformSettings(profile='local', local_demo_python=True))


def test_local_platform_does_not_enable_unisolated_python_runner():
    from server.assessment.runner import JudgeRunner
    from server.platform import create_app
    from server.platform_settings import PlatformSettings
    from server.providers.base import GenerationError

    settings = PlatformSettings(profile="local")
    app = create_app(settings)
    assert not settings.checks()["python_runner"]
    assert isinstance(app.state.runner, JudgeRunner)
    with pytest.raises(GenerationError, match="separate isolated Python runner"):
        app.state.runner.ready()
    app.state.runner.close()


def test_password_hash_round_trip():
    stored = hash_password("correct horse")
    assert check_password("correct horse", stored) and not check_password("wrong horse", stored)


def test_local_runner_grades_stdin_programs(monkeypatch):
    monkeypatch.setenv("PLATFORM_PROFILE", "local")
    key = {"tests": [{"stdin": "2 3\n", "expected": "5", "category": "sum"}], "hints": ["Add them"], "explanation": "Read two ints and add."}
    runner = demo_runner()
    good = runner.poll(runner.submit("a, b = map(int, input().split())\nprint(a + b)", key), key)
    bad = runner.poll(runner.submit("print(0)", key), key)
    assert good["passed"] and not bad["passed"] and bad["failed_categories"] == ["sum"]


def test_local_runner_refused_outside_local_profile(monkeypatch):
    monkeypatch.setenv("PLATFORM_PROFILE", "production")
    with pytest.raises(Exception):
        LocalRunner().ready()


def test_local_object_store_signs_and_rejects_traversal(tmp_path):
    store, source = LocalObjectStore(tmp_path / "objects"), tmp_path / "a.txt"
    source.write_text("hello")
    store.put("lessons/x/a.txt", source, "text/plain")
    url = store.sign("lessons/x/a.txt")
    assert url.startswith("/api/local/objects/lessons/x/a.txt?expires=") and "signature=" in url
    with pytest.raises(ValueError):
        store.path("../escape.txt")


def test_new_visual_kinds_and_short_answer_contract():
    VisualSpec(kind="compare", caption="Lists vs tuples", headers=["", "list", "tuple"], rows=[["mutable", "yes", "no"]])
    with pytest.raises(ValueError):
        VisualSpec(kind="array", caption="Search", items=["1", "2"], pointers=[{"index": 5}])
    question = {"kind": "short", "prompt": "Why is binary search O(log n)?"}
    key = {"hints": ["Think about halving"], "explanation": "Each step halves the range.", "model_answer": "It halves the range each step.", "rubric": ["halves the search range"]}
    PlannedAssessment(objective_id="o0", variant="base", question=question, key=key)
    with pytest.raises(ValueError):
        PlannedAssessment(objective_id="o0", variant="base", question=question, key={**key, "rubric": []})


def test_first_assessment_prepares_adapted_fourth_block(platform):  # noqa: F811
    client, factory, ids = platform
    _, curriculum = seed_lesson(factory, ids, count=4)
    session = finish_clip(client, start(client, curriculum))
    response = client.post("/api/attempts", headers=headers("alice"), json=answer_body(session, "no"))
    assert response.status_code == 202, response.text
    with factory() as db:
        jobs = db.scalars(select(Job).where(Job.kind == "block")).all()
    adapted = [x for x in jobs if x.payload["profile"] == "adapted"]
    assert len(adapted) == 1 and adapted[0].payload["objective_id"] == "o3"
    assert adapted[0].payload["performance"][0]["first_attempt_passed"] is False


def test_scene_repairs_model_step_numbering():
    from server.lessons.contracts import InstructionScene
    visual = {"kind": "code_trace", "caption": "Trace a two-step update of the total.", "code_lines": ["total = 0", "total += 2"],
              "trace": [{"line": 1, "variables": {"total": "0"}}, {"line": 2, "variables": {"total": "2"}}]}
    def steps(given):
        scene = InstructionScene(id="s", title="Repair steps", bullets=["One"], visual=visual,
            utterances=[{"text": f"Narration line number {i} for the scene.", "visual_step": s} for i, s in enumerate(given)])
        return [u.visual_step for u in scene.utterances]
    assert steps([1, 2, 3]) == [0, 1, 2]       # 1-based
    assert steps([0, 9]) == [0, 2]             # past the end
    assert steps([0, 2, 1]) == [0, 2, 2]       # decreasing
    assert steps([0, 0, 0]) == [0, 1, 2]       # never advancing


def test_stray_choice_key_on_python_task_reports_missing_tests():
    from pydantic import ValidationError
    body = {"objective_id": "o1", "variant": "base",
            "question": {"kind": "python", "prompt": "Write binary search returning the index or -1."},
            "key": {"correct": ["a", "b"], "hints": ["Halve the range"], "explanation": "Compare with the middle element."}}
    with pytest.raises(ValidationError, match="test cases and a reference solution"):
        PlannedAssessment.model_validate(body)


def test_gemini_schema_drops_only_length_bounds():
    from server.lessons.authoring import gemini_schema
    from server.lessons.contracts import BlockDraft
    text = str(gemini_schema(BlockDraft.model_json_schema()))
    assert "maxLength" not in text and "minItems" not in text and "visual_step" in text and "required" in text


def test_code_trace_must_be_python():
    from pydantic import ValidationError
    trace = [{"line": 1, "variables": {"i": "0"}}]
    with pytest.raises(ValidationError, match="valid Python 3"):
        VisualSpec(kind="code_trace", caption="A C++ loop that cannot be verified.", code_lines=["int i = 0;"], trace=trace)
    VisualSpec(kind="code_trace", caption="A Python loop that the runner can verify.", code_lines=["i = 0"], trace=trace)


def test_measured_trace_replaces_hand_computed_values(monkeypatch):
    from server.assessment.trace_validation import measured_trace, trace_harness
    monkeypatch.setenv("PLATFORM_PROFILE", "local")
    runner = demo_runner()
    visual = VisualSpec(kind="code_trace", caption="Count the items that are at most the pivot.",
        code_lines=["A = [3, 1, 2, 6]", "i = 0", "for j in range(3):", "    if A[j] <= 6:", "        i += 1", "done = i"],
        trace=[{"line": 2, "variables": {"i": "0"}}, {"line": 6, "variables": {"i": "0", "done": "9"}, "array": ["9"], "array_name": "A"}])
    assert runner.run(trace_harness(visual), "")[1].strip() == "TRACE_MISMATCH"
    fixed = measured_trace(visual, runner.run)
    assert fixed.trace[1].variables == {"i": "3", "done": "3"} and fixed.trace[1].array == ["3", "1", "2", "6"]
    assert runner.run(trace_harness(fixed), "")[1].strip() == "TRACE_OK"


def test_exact_output_accepts_print_newline_on_windows(monkeypatch):
    from server.assessment.grading import matches
    monkeypatch.setenv("PLATFORM_PROFILE", "local")
    key = {"tests": [{"stdin": "4 7 9", "expected": "9", "category": "last"}], "comparison": "exact", "hints": ["Use -1"], "explanation": "Index -1 is the last item."}
    runner = demo_runner()
    assert runner.poll(runner.submit("print(input().split()[-1])", key), key)["passed"]
    assert not matches("9 \n", "9", "exact")
