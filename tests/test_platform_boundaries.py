import base64
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from pydantic import ValidationError

from server.auth import SupabaseVerifier
from server.assessment.grading import grade, matches
from server.assessment.runner import JudgeRunner
from server.ingestion.readers import extract_document, youtube_id
from server.lessons.contracts import CurriculumPlan
from server.platform_settings import PlatformSettings
from server.providers.base import GenerationError
from server.visuals import RenderRequest, VisualSpec


@pytest.mark.parametrize("url", ["http://youtube.com/watch?v=abcdefghijk", "https://youtube.com.evil.test/watch?v=abcdefghijk", "https://127.0.0.1/watch?v=abcdefghijk", "https://user:pass@youtube.com/watch?v=abcdefghijk", "https://youtu.be/abc", "https://youtube.com:8443/watch?v=abcdefghijk"])
def test_video_urls_cannot_become_general_network_requests(url):
    with pytest.raises(GenerationError):
        youtube_id(url)


def test_valid_video_url_is_canonicalized():
    assert youtube_id("https://youtu.be/abcdefghijk?t=20") == "abcdefghijk"
    assert youtube_id("https://www.youtube.com/watch?v=abcdefghijk&list=irrelevant") == "abcdefghijk"


@pytest.mark.parametrize("actual,expected,comparison,result", [("nan", "1", "numeric", False), ("inf", "inf", "numeric", False),
    ("1.0000001", "1", "numeric", True), ("1 2", "1", "numeric", False), ("  x\n", "x", "exact", False), ("x  \n", "x", "trim_lines", True)])
def test_grading_comparison_is_explicit(actual, expected, comparison, result):
    assert matches(actual, expected, comparison) is result


def test_choice_grading_rejects_injected_option_ids():
    with pytest.raises(ValueError):
        grade({"kind": "mcq", "options": [{"id": "a"}, {"id": "b"}]}, {"correct": ["a"], "hints": ["A hint"], "explanation": "An explicit explanation"}, {"choice": "../../key"})


@pytest.mark.parametrize("change", ["expired", "issuer", "audience", "session", "none"])
def test_supabase_token_requires_signed_expected_claims(change, monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    settings = PlatformSettings(supabase_url="https://auth.example.test", supabase_public_key="public-test-key")
    verifier = SupabaseVerifier(settings)
    verifier.jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private.public_key()))
    identifier = str(uuid4())
    claims = {"sub": identifier, "exp": int(time.time()) + 600, "iat": int(time.time()), "aud": "authenticated",
              "iss": settings.supabase_url + "/auth/v1", "session_id": str(uuid4())}
    if change == "expired": claims["exp"] = int(time.time()) - 120
    if change == "issuer": claims["iss"] = "https://wrong-issuer.example"
    if change == "audience": claims["aud"] = "another-application"
    if change == "session": claims.pop("session_id")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"id": identifier, "email": "learner@example.test", "user_metadata": {"role": "administrator"}}, request=httpx.Request("GET", settings.supabase_url)))
    token = jwt.encode(claims, private, algorithm="ES256")
    if change == "none":
        actor = verifier(token)
        assert actor.id == identifier and not hasattr(actor, "privilege")
    else:
        with pytest.raises(HTTPException) as failure:
            verifier(token)
        assert failure.value.status_code == 401


def key_fixture():
    return {"tests": [{"stdin": "1\n", "expected": "2\n", "category": "boundary", "essential": True}],
            "reference_solution": "print(int(input()) + 1)", "hints": ["Review the boundary."], "explanation": "The expected boundary result is two."}


def test_runner_sets_limits_and_keeps_expected_values_on_backend():
    runner = JudgeRunner(PlatformSettings(runner_url="https://runner.example.test", runner_language_id=71, runner_token="private-test-token", runner_verified=True))
    sent = []
    def respond(request):
        if request.method == "POST":
            body = json.loads(request.content); sent.append(body)
            return httpx.Response(201, json={"token": "owned-runner-token"})
        return httpx.Response(200, json={"status": {"id": 3}, "stdout": base64.b64encode(b"2\n").decode()})
    runner.client.close(); runner.client = httpx.Client(transport=httpx.MockTransport(respond))
    tokens = runner.submit("print(int(input()) + 1)", key_fixture())
    assert sent[0]["enable_network"] is False
    assert sent[0]["cpu_time_limit"] == 2 and sent[0]["wall_time_limit"] == 5
    assert sent[0]["memory_limit"] == 131072 and sent[0]["max_file_size"] == 64
    assert "expected_output" not in sent[0] and "reference_solution" not in sent[0]
    assert runner.poll(tokens, key_fixture())["passed"]
    runner.close()


def test_runner_failure_is_not_a_wrong_answer():
    runner = JudgeRunner(PlatformSettings(runner_url="https://runner.example.test", runner_language_id=71, runner_verified=True))
    runner.client.close(); runner.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"status": {"id": 13}})))
    with pytest.raises(GenerationError, match="grading service failed"):
        runner.poll(["token"], key_fixture())
    runner.close()


def test_runner_is_disabled_until_actual_isolation_is_verified():
    runner = JudgeRunner(PlatformSettings(runner_url="https://runner.example.test", runner_language_id=71))
    with pytest.raises(GenerationError, match="verify"):
        runner.ready()
    runner.close()


def trace_visual():
    return {"kind": "code_trace", "caption": "A displayed trace, never executed.",
            "code_lines": ["total = 0", "for value in [2, 3]:", "    total += value"],
            "trace": [{"line": 1, "variables": {"total": "0"}}, {"line": 3, "variables": {"total": "2"}, "array": ["2", "3"], "active_index": 0},
                      {"line": 3, "variables": {"total": "5"}, "array": ["2", "3"], "active_index": 1}]}


def test_code_trace_rejects_nonexistent_lines_cells_and_nonsemantic_cues():
    visual = trace_visual()
    VisualSpec.model_validate(visual)
    visual["trace"][0]["line"] = 12
    with pytest.raises(ValidationError): VisualSpec.model_validate(visual)
    visual = trace_visual(); visual["trace"][1]["active_index"] = 9
    with pytest.raises(ValidationError): VisualSpec.model_validate(visual)
    with pytest.raises(ValidationError):
        RenderRequest(title="Invalid cue order", visual=trace_visual(), duration=10, scene_number=1, total=8, cue_times=[.1, 5], cue_steps=[2, 0])


def test_imports_reject_mislabeled_files_and_flag_scanned_pages(tmp_path):
    fake = tmp_path / "fake.pdf"; fake.write_bytes(b"This is not a PDF")
    with pytest.raises(GenerationError, match="not a PDF"): extract_document(fake, "pdf")
    from pypdf import PdfWriter
    blank = tmp_path / "scan.pdf"; writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    with blank.open("wb") as out: writer.write(out)
    evidence, warnings = extract_document(blank, "pdf")
    assert len(evidence) == 1 and evidence[0]["uncertainty"] == ["ocr_required"] and warnings[0]["critical"]


def test_repaired_curriculum_cannot_drop_coverage_or_introduce_a_cycle():
    obj = {"id": "a", "title": "A concept", "description": "Explain the concept fully", "prerequisites": ["a"],
           "evidence": [{"source_version_id": str(uuid4()), "block_id": "source-1"}],
           "worked_example": "A complete worked example", "visual_approach": "Code trace"}
    q = {"objective_id": "a", "variant": "base", "question": {"kind": "trace", "prompt": "Predict the output of this example.", "starter_code": "print(1)"},
         "key": {"expected_output": "1", "hints": ["Follow the trace"], "explanation": "The loop runs exactly one time."}}
    with pytest.raises(ValidationError, match="Prerequisites"):
        CurriculumPlan.model_validate({"title": "Full lesson", "scope": "A fully sourced scope", "objectives": [obj], "assessments": [q, {**q, "variant": "equivalent"}]})
    obj["prerequisites"] = []
    with pytest.raises(ValidationError, match="base and one equivalent"):
        CurriculumPlan.model_validate({"title": "Full lesson", "scope": "A fully sourced scope", "objectives": [obj], "assessments": [q, q]})


def test_trace_checker_detects_incorrect_illustrated_values():
    # This is hand-authored, trusted fixture code only. Production sends all
    # generated/learner programs to Judge0 and has no local execution fallback.
    import subprocess
    import sys
    from server.assessment.trace_validation import trace_harness
    visual = VisualSpec.model_validate({"kind": "code_trace", "caption": "A deterministic fixture trace",
        "code_lines": ["values = [2, 3]", "total = 0", "for index in range(len(values)):", "    total += values[index]"],
        "trace": [{"line": 2, "variables": {"total": "0"}}, {"line": 4, "variables": {"total": "2"}, "array": ["2", "3"], "array_name": "values", "index_variable": "index", "active_index": 0},
                  {"line": 4, "variables": {"total": "5"}, "array": ["2", "3"], "array_name": "values", "index_variable": "index", "active_index": 1}]})
    result = subprocess.run([sys.executable, "-c", trace_harness(visual)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "TRACE_OK"
    visual.trace[-1].variables["total"] = "6"
    result = subprocess.run([sys.executable, "-c", trace_harness(visual)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == "TRACE_MISMATCH"
