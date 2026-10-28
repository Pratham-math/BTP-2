"""Executable checkpoint repairs use fixed private fixtures, never live AI."""
from types import SimpleNamespace

import pytest

from server.lessons.contracts import CurriculumPlan, PlannedAssessment, Verification, digest
from server.platform_settings import PlatformSettings
from server.local_services import LocalRunner
from server.providers.base import GenerationError
from server.worker.tasks import validate_questions


def assessment(code="def forecast_value(x, beta_0, beta_1):\n    return beta_0 + beta_1*x"):
    return PlannedAssessment(objective_id="forecast", variant="base",
        question={"kind": "python", "prompt": "Read x, intercept and slope, then print the forecast."},
        key={"reference_solution": code, "tests": [{"stdin": "2 1 3\n", "expected": "7.0", "category": "basic"}],
             "hints": ["Apply intercept plus slope times x."], "explanation": "The forecast is the intercept plus slope times x."})


GOOD = "x, b0, b1 = map(float, input().split())\nprint(b0 + b1*x)"


def fixture():
    first = assessment()
    second = assessment(GOOD).model_copy(update={"variant": "equivalent"})
    plan = CurriculumPlan(title="Forecasting", scope="Compute a simple linear regression prediction.", objectives=[{
        "id": "forecast", "title": "Forecast a value", "description": "Apply intercept plus slope times x.",
        "prerequisites": [], "evidence": [{"source_version_id": "source", "block_id": "one"}],
        "worked_example": "For x=2, intercept=1, slope=3, the forecast is 7.", "visual_approach": "Show the formula."}],
        assessments=[first, second])
    packets = [{"id": "source", "evidence": [{"id": "one", "text": "y = intercept + slope*x"}]}]
    return plan, packets


class Context:
    def __init__(self):
        self.records = {}
    def check(self):
        pass
    def saved(self, stage, inputs):
        return self.records.get((stage, digest(inputs)))
    def save(self, stage, inputs, value):
        self.records[(stage, digest(inputs))] = value


class Author:
    settings = PlatformSettings(profile="local", local_demo_python=True, text_model="fixture", verifier_model="fixture")
    def __init__(self, repair=None):
        self.repairs = []
        self.repair = repair or assessment(GOOD)
    def ask(self, stage, model, contract, task, data):
        if contract is Verification:
            return Verification(findings=[], evidence_checked=True, objective_covered=True, example_consistent=True)
        self.repairs.append((stage, data))
        return self.repair.model_copy(deep=True)


def test_function_only_reference_is_repaired_and_retested(tmp_path, monkeypatch):
    import server.local_services as services
    monkeypatch.setattr(services, "LOCAL_TEMP", tmp_path)
    plan, packets = fixture()
    plan.assessments[0].key.tests[0].stdin = "print(forecast_value(2.0, 1.0, 3.0))"
    author, runner, context = Author(), LocalRunner(Author.settings), Context()
    validate_questions(plan, packets, author, runner, context)
    assert len(author.repairs) == 1
    assert author.repairs[0][1]["validation_findings"]["solution"] == "reference"
    assert plan.assessments[0].key.reference_solution == GOOD
    assert plan.assessments[0].key.tests[0].expected == "7.0"
    assert plan.assessments[0].key.tests[0].stdin == "2 1 3"
    # Completed validation does not request another repair or re-run the runner.
    runner.submit = lambda *args: pytest.fail("Validated checkpoint should be reused")
    validate_questions(plan, packets, author, runner, context)
    assert len(author.repairs) == 1


def test_failed_reference_never_rewrites_expected_outputs():
    plan, packets = fixture()
    plan.assessments[0].key.reference_solution = "print('wrong')"
    author = Author(repair=plan.assessments[0])
    class Runner:
        def run(self, *args):
            pytest.fail("Reference output must not become the answer key")
        def submit(self, *args):
            return ["fixture"]
        def poll(self, *args):
            return {"passed": False, "score": 0, "failed_categories": ["basic"]}
    with pytest.raises(GenerationError, match="after two repairs"):
        validate_questions(plan, packets, author, Runner(), Context())
    assert len(author.repairs) == 2
    assert plan.assessments[0].key.tests[0].expected == "7.0"


@pytest.mark.parametrize("change", [{"objective_id": "other"}, {"variant": "equivalent"}])
def test_repair_cannot_change_fixed_scope(change):
    plan, packets = fixture()
    author = Author(assessment(GOOD).model_copy(update=change))
    runner = SimpleNamespace(submit=lambda *args: ["fixture"], poll=lambda *args: {"passed": False, "score": 0})
    with pytest.raises(GenerationError) as caught:
        validate_questions(plan, packets, author, runner, Context())
    assert caught.value.code == "INVALID_ASSESSMENT_SCOPE"


@pytest.mark.parametrize("wrong_solution", [False, True])
def test_validation_rejects_partial_references_and_accepted_wrong_programs(wrong_solution):
    plan, packets = fixture()
    if wrong_solution:
        plan.assessments[0].key.known_wrong_solutions = ["print('wrong')"]
    author = Author(plan.assessments[0])
    runner = SimpleNamespace(submit=lambda *args: ["fixture"],
        poll=lambda *args: {"passed": True, "score": 1 if wrong_solution else .8})
    with pytest.raises(GenerationError, match="after two repairs"):
        validate_questions(plan, packets, author, runner, Context())
    assert len(author.repairs) == 2


def test_runner_infrastructure_failure_does_not_trigger_model_repairs():
    plan, packets = fixture()
    author = Author()
    def unavailable(*args):
        raise GenerationError("RUNNER_NOT_VERIFIED", "Configure the runner.")
    runner = SimpleNamespace(submit=unavailable)
    with pytest.raises(GenerationError) as caught:
        validate_questions(plan, packets, author, runner, Context())
    assert caught.value.code == "RUNNER_NOT_VERIFIED"
    assert not author.repairs


def test_alternative_solution_is_checked_in_local_demo_too():
    plan, packets = fixture()
    plan.assessments[0].key.reference_solution = GOOD
    plan.assessments[0].key.alternative_solution = "print('wrong')"
    author = Author()
    current = []
    def submit(code, key):
        current[:] = [code]
        return ["fixture"]
    runner = SimpleNamespace(submit=submit,
        poll=lambda *args: {"passed": current[0] == GOOD, "score": 1 if current[0] == GOOD else 0})
    validate_questions(plan, packets, author, runner, Context())
    assert len(author.repairs) == 1
    assert author.repairs[0][1]["validation_findings"]["solution"] == "alternative"
