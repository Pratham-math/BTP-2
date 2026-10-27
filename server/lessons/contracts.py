"""Typed educational content. Generation cannot change scope while repairing a block."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from server.visuals import VisualSpec, visual_step_count


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class EvidenceBlock(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    text: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=20000)
    location: str = Field(min_length=1, max_length=160)
    method: str = Field(max_length=40)
    uncertainty: list[str] = Field(default_factory=list, max_length=30)
    image_key: str | None = None

    @field_validator("text")
    @classmethod
    def readable_text(cls, value):
        if not value.strip():
            raise ValueError("An evidence block must contain readable text")
        return value


class EvidenceRef(Contract):
    source_version_id: str
    block_id: str


class Objective(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=2000)
    prerequisites: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(min_length=1)
    worked_example: str = Field(min_length=10, max_length=4000)
    visual_approach: str = Field(min_length=5, max_length=400)
    check_kind: Literal["mcq", "multiple", "trace", "python", "short"] = Field(default="mcq", description=
        "How to test this objective: python if the learner must write Python code (Write/Implement; the grader runs only Python 3, "
        "so for other languages use trace or short),trace if they must read code "
        "and predict its output, short for explain/why/compare, multiple for picking several true properties, mcq otherwise")


class Option(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    text: str = Field(min_length=1, max_length=500)


class Question(Contract):
    kind: Literal["mcq", "multiple", "trace", "python", "short"]
    prompt: str = Field(min_length=10, max_length=5000)
    options: list[Option] = Field(default_factory=list, max_length=12)
    starter_code: str = Field(default="", max_length=12000)
    public_examples: list[dict[str, str]] = Field(default_factory=list, max_length=5)


class TestCase(Contract):
    stdin: str = Field(max_length=16000)
    expected: str = Field(max_length=16000)
    category: str = Field(min_length=1, max_length=64)
    essential: bool = True
    weight: int = Field(default=1, ge=1, le=10)


class GradingKey(Contract):
    correct: list[str] = Field(default_factory=list)
    expected_output: str = Field(default="", max_length=16000)
    comparison: Literal["exact", "trim_lines", "numeric"] = "trim_lines"
    tolerance: float = Field(default=1e-6, gt=0, le=.01)
    tests: list[TestCase] = Field(default_factory=list, max_length=12)
    reference_solution: str = Field(default="", max_length=16000)
    alternative_solution: str = Field(default="", max_length=16000)
    known_wrong_solutions: list[str] = Field(default_factory=list, max_length=5)
    hints: list[str] = Field(min_length=1, max_length=3)
    explanation: str = Field(min_length=10, max_length=4000)
    misconception_map: dict[str, str] = Field(default_factory=dict)
    model_answer: str = Field(default="", max_length=4000)
    rubric: list[str] = Field(default_factory=list, max_length=6)


class PlannedAssessment(Contract):
    objective_id: str
    variant: Literal["base", "equivalent"]
    question: Question
    key: GradingKey

    @model_validator(mode="after")
    def key_matches_question(self):
        q, k = self.question, self.key
        ids = [x.id for x in q.options]
        if len(ids) != len(set(ids)):
            raise ValueError("Option IDs must be unique")
        if q.kind in {"mcq", "multiple"}:
            # Models often answer with the option's text, letter or position instead of
            # its ID. Map only unambiguous forms; anything else still fails below.
            def option_id(value):
                text = value.strip()
                for option in q.options:
                    if text.lower() in {option.id.lower(), option.text.strip().lower()}:
                        return option.id
                if len(text) == 1 and text.isalpha() and ord(text.upper()) - 65 < len(ids):
                    return ids[ord(text.upper()) - 65]
                return value
            k.correct = list(dict.fromkeys(option_id(x) for x in k.correct))
            k.misconception_map = {option_id(key): tag for key, tag in k.misconception_map.items()}
        if q.kind in {"mcq", "multiple"}:
            if len(ids) < 2 or not k.correct or not set(k.correct).issubset(ids):
                raise ValueError("Choice keys must reference existing options")
            if q.kind == "mcq" and len(k.correct) != 1:
                raise ValueError("MCQ requires exactly one correct choice")
        elif q.options:
            raise ValueError("Trace, Python and short-answer questions do not have choice options")
        elif k.correct:
            # A choice key without options is a model slip; drop it so the real gap (tests, answer) is reported.
            k.correct, k.misconception_map = [], {}
        if q.kind == "short" and (not k.model_answer or not k.rubric):
            raise ValueError("Short-answer questions require a model answer and 1-6 rubric points")
        if q.kind == "python" and (not k.tests or not k.reference_solution):
            raise ValueError("Python tasks require test cases and a reference solution")
        if q.kind == "trace" and not k.expected_output:
            raise ValueError("Trace tasks require an expected output")
        return self


class CurriculumPlan(Contract):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=3, max_length=160)
    scope: str = Field(min_length=10, max_length=4000)
    prerequisites: list[str] = Field(default_factory=list)
    notation: dict[str, str] = Field(default_factory=dict)
    objectives: list[Objective] = Field(min_length=1)
    assessments: list[PlannedAssessment] = Field(min_length=2)
    source_coverage: list['SourceCoverage'] = Field(default_factory=list)
    planning_batches: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def complete_graph(self):
        ids = [x.id for x in self.objectives]
        if len(ids) != len(set(ids)):
            raise ValueError("Objective IDs must be unique")
        seen = set()
        for objective in self.objectives:
            if not set(objective.prerequisites).issubset(seen):
                raise ValueError("Prerequisites must precede their dependent objective; cycles are forbidden")
            seen.add(objective.id)
        assessment_pairs = [(x.objective_id, x.variant) for x in self.assessments]
        expected = {(oid, variant) for oid in ids for variant in ("base", "equivalent")}
        if len(assessment_pairs) != len(expected) or set(assessment_pairs) != expected:
            raise ValueError("Every objective needs exactly one base and one equivalent checkpoint")
        if self.source_coverage:
            actual = {}
            for objective in self.objectives:
                for ref in objective.evidence:
                    actual.setdefault((ref.source_version_id, ref.block_id), set()).add(objective.id)
            covered = set()
            for entry in self.source_coverage:
                ref = (entry.source_version_id, entry.block_id)
                if ref in covered or set(entry.objective_ids) != actual.get(ref, set()):
                    raise ValueError("Source coverage must be unique and match objective evidence")
                covered.add(ref)
            if not set(actual).issubset(covered):
                raise ValueError("Every cited source section needs a coverage record")
        return self

    def public_blueprint(self):
        # The immutable public curriculum has assessment references, never keys.
        return self.model_dump(exclude={"assessments"})


class SourceCoverage(EvidenceRef):
    objective_ids: list[str] = Field(default_factory=list)
    exclusion_reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def disposition(self):
        if bool(self.objective_ids) == bool(self.exclusion_reason):
            raise ValueError("A source section must be included or have an explicit exclusion reason")
        return self


class CurriculumHeader(Contract):
    title: str = Field(min_length=3, max_length=160)
    scope: str = Field(min_length=10, max_length=4000)
    prerequisites: list[str] = Field(default_factory=list, max_length=40)
    notation: dict[str, str] = Field(default_factory=dict, max_length=60)


class ExcludedEvidence(EvidenceRef):
    reason: str = Field(min_length=10, max_length=1000)


class ObjectiveBatch(Contract):
    objectives: list[Objective] = Field(max_length=12)
    excluded: list[ExcludedEvidence] = Field(default_factory=list)


class AssessmentPair(Contract):
    assessments: list[PlannedAssessment] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def pair(self):
        if (len({x.objective_id for x in self.assessments}) != 1
                or {x.variant for x in self.assessments} != {"base", "equivalent"}):
            raise ValueError("Return a base and a fresh equivalent check for exactly one objective")
        return self


class Utterance(Contract):
    text: str = Field(min_length=3, max_length=1000)
    visual_step: int = Field(default=0, ge=0, le=100)


class InstructionScene(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    title: str = Field(min_length=3, max_length=60)
    bullets: list[str] = Field(min_length=1, max_length=3)
    utterances: list[Utterance] = Field(min_length=1, max_length=30)
    visual: VisualSpec

    @model_validator(mode="after")
    def semantic_steps(self):
        # Steps only time when visuals appear, so repair common model slips (1-based,
        # out of range, decreasing, never advancing) instead of rejecting the scene.
        total, steps = visual_step_count(self.visual), [x.visual_step for x in self.utterances]
        fixed, high = [], 0
        for step in steps:
            high = min(max(high, step - steps[0]), total - 1)
            fixed.append(high)
        if len(fixed) > 1 and len(set(fixed)) == 1 and total > 1:
            fixed = [round(i * (total - 1) / (len(fixed) - 1)) for i in range(len(fixed))]
        for utterance, step in zip(self.utterances, fixed):
            utterance.visual_step = step
        return self

    @property
    def narration(self):
        return " ".join(x.text for x in self.utterances)


class BlockDraft(Contract):
    objective_id: str
    profile: Literal["normal", "reinforced", "recap", "adapted"]
    explanation: str = Field(min_length=20, max_length=8000)
    worked_example: str = Field(min_length=10, max_length=6000)
    source_refs: list[EvidenceRef] = Field(min_length=1)
    scenes: list[InstructionScene] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_scenes(self):
        if len({x.id for x in self.scenes}) != len(self.scenes):
            raise ValueError("Scene IDs must be unique within a block")
        return self


class Finding(Contract):
    severity: Literal["critical", "warning"]
    category: Literal["factual", "coverage", "source", "example", "assessment", "visual", "pedagogy"]
    message: str = Field(min_length=10, max_length=2000)


class Verification(Contract):
    findings: list[Finding]
    evidence_checked: bool
    objective_covered: bool
    example_consistent: bool

    def accepted(self):
        return (self.evidence_checked and self.objective_covered and self.example_consistent
                and not any(x.severity == "critical" for x in self.findings))
