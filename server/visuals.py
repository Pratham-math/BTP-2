"""Bounded scene data shared by Gemini validation and the local Manim renderer."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class VisualModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class VisualNode(VisualModel):
    id: str = Field(min_length=1, max_length=12)
    label: str = Field(min_length=1, max_length=28)
    icon: Literal["none", "sun", "plant", "water", "cloud", "computer"] = "none"
    color: Literal["teal", "blue", "amber", "red", "ink"] = "teal"


class VisualEdge(VisualModel):
    source: str
    target: str


class PlotPoint(VisualModel):
    x: float = Field(ge=-1000, le=1000)
    y: float = Field(ge=-1000, le=1000)


class TraceStep(VisualModel):
    line: int = Field(ge=1, le=12, description="The Python line just executed; variables describe its resulting state")
    variables: dict[str, str] = Field(default_factory=dict, max_length=6)
    array: list[str] = Field(default_factory=list, max_length=10)
    active_index: int | None = Field(default=None, ge=0, le=9)
    array_name: str = Field(default="", max_length=16)
    index_variable: str = Field(default="", max_length=16)

    @model_validator(mode="after")
    def bounded_state(self):
        if any(len(k) > 16 or len(v) > 36 for k, v in self.variables.items()) or any(len(x) > 12 for x in self.array):
            raise ValueError("Trace state labels exceed readable display bounds")
        if self.active_index is not None and self.active_index >= len(self.array):
            raise ValueError("Highlighted array index must exist")
        return self


class ArrayPointer(VisualModel):
    index: int = Field(ge=0, le=9)
    note: str = Field(default="", max_length=60)


TEXT_KINDS = {"bullets", "equation"}


class VisualSpec(VisualModel):
    kind: Literal["process", "cycle", "tree", "plot", "code_trace", "bullets", "compare", "array", "equation"]
    caption: str = Field(min_length=1, max_length=110)
    nodes: list[VisualNode] = Field(default_factory=list, max_length=7)
    edges: list[VisualEdge] = Field(default_factory=list, max_length=8)
    points: list[PlotPoint] = Field(default_factory=list, max_length=12)
    x_label: str = Field(default="", max_length=24)
    y_label: str = Field(default="", max_length=24)
    fit_line: bool = False
    code_lines: list[Annotated[str, StringConstraints(strip_whitespace=False)]] = Field(default_factory=list, max_length=12)
    trace: list[TraceStep] = Field(default_factory=list, max_length=30)
    items: list[Annotated[str, StringConstraints(max_length=120)]] = Field(default_factory=list, max_length=8,
        description="bullets: points revealed one by one; equation: LaTeX lines; array: cell values")
    headers: list[Annotated[str, StringConstraints(max_length=32)]] = Field(default_factory=list, max_length=3,
        description="compare: 2 or 3 column headings")
    rows: list[list[Annotated[str, StringConstraints(max_length=60)]]] = Field(default_factory=list, max_length=6,
        description="compare: rows with one cell per heading")
    pointers: list[ArrayPointer] = Field(default_factory=list, max_length=20,
        description="array: successive highlighted indices with a short note")

    @model_validator(mode="after")
    def check_diagram(self):
        extra = {"items": self.items, "headers": self.headers, "rows": self.rows, "pointers": self.pointers}
        allowed = {"bullets": {"items"}, "equation": {"items"}, "array": {"items", "pointers"}, "compare": {"headers", "rows"}}.get(self.kind, set())
        if any(value and name not in allowed for name, value in extra.items()):
            raise ValueError(f"{self.kind} visuals do not use {', '.join(n for n, v in extra.items() if v and n not in allowed)}")
        if self.kind in allowed_kinds_without_graph():
            if self.nodes or self.edges or self.points or self.code_lines or self.trace:
                raise ValueError(f"{self.kind} visuals do not use graph, plot or code fields")
            if self.kind in TEXT_KINDS and not 1 <= len(self.items) <= 6:
                raise ValueError(f"{self.kind} visuals need 1 to 6 items")
            if self.kind == "array":
                if not 2 <= len(self.items) <= 10 or any(len(x) > 12 for x in self.items) or not self.pointers:
                    raise ValueError("Arrays need 2 to 10 short cells and at least one pointer step")
                if any(p.index >= len(self.items) for p in self.pointers):
                    raise ValueError("Array pointers must reference existing cells")
            if self.kind == "compare":
                if len(self.headers) not in {2, 3} or not 1 <= len(self.rows) <= 6 or any(len(r) != len(self.headers) for r in self.rows):
                    raise ValueError("Comparisons need 2-3 headings and 1-6 rows with one cell per heading")
            return self
        if self.kind == "code_trace":
            if not self.code_lines or not self.trace or any(len(line) > 60 for line in self.code_lines):
                raise ValueError("Code traces require up to 12 short code lines and measured trace states")
            if self.nodes or self.edges or self.points or self.fit_line:
                raise ValueError("Code traces use code lines and state, not graph or plot fields")
            if any(step.line > len(self.code_lines) for step in self.trace):
                raise ValueError("Trace highlights must reference existing code lines")
            try:
                # Compile only (never executed here): the runner can verify Python traces alone.
                compile("\n".join(self.code_lines), "<teaching-example>", "exec")
            except (SyntaxError, ValueError):
                raise ValueError("code_trace code must be valid Python 3 because the runner verifies it; "
                                 "translate other languages to Python or use an array visual") from None
            return self
        if self.code_lines or self.trace:
            raise ValueError("Only code_trace visuals use code and state fields")
        if self.kind == "plot":
            if len(self.points) < 2 or not self.x_label or not self.y_label:
                raise ValueError("Plots need at least two points and both axis labels")
            if self.nodes or self.edges:
                raise ValueError("Plots use points, not nodes or edges")
            if self.fit_line and len({point.x for point in self.points}) < 2:
                raise ValueError("A fitted line needs at least two distinct x values")
            return self

        if not 2 <= len(self.nodes) <= (7 if self.kind == "tree" else 6):
            raise ValueError("Diagrams need 2 to 6 nodes; trees allow up to 7")
        if self.points or self.fit_line:
            raise ValueError("Only plots support points or fitted lines")
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Node IDs must be unique")
        pairs = [(edge.source, edge.target) for edge in self.edges]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate edges are not allowed")
        if any(a not in ids or b not in ids or a == b for a, b in pairs):
            raise ValueError("Edges must connect different, existing node IDs")

        if self.kind in {"process", "cycle"}:
            expected = set(zip(ids, ids[1:]))
            if self.kind == "cycle":
                expected.add((ids[-1], ids[0]))
            if set(pairs) != expected:
                raise ValueError("Connect nodes in list order, closing the loop only for a cycle")
        else:
            children = {node_id: [] for node_id in ids}
            parents = {node_id: 0 for node_id in ids}
            for source, target in pairs:
                children[source].append(target)
                parents[target] += 1
            roots = [node_id for node_id in ids if parents[node_id] == 0]
            if len(roots) != 1 or any(count > 1 for count in parents.values()):
                raise ValueError("A tree needs one root and one parent per other node")
            visited = set()

            def visit(node_id, depth):
                if node_id in visited or depth > 3:
                    raise ValueError("Trees must be acyclic with at most four levels")
                visited.add(node_id)
                for child in children[node_id]:
                    visit(child, depth + 1)

            visit(roots[0], 0)
            if len(visited) != len(ids):
                raise ValueError("All tree nodes must be connected")
        return self


class RenderRequest(VisualModel):
    title: str = Field(min_length=3, max_length=60)
    visual: VisualSpec
    duration: float = Field(ge=0.5, le=300)
    scene_number: int = Field(ge=1)
    total: int = Field(ge=1)
    render_profile: Literal["720p24", "480p24"] = "720p24"
    cue_times: list[float] = Field(default_factory=list, max_length=120)
    cue_steps: list[int] = Field(default_factory=list, max_length=120)

    @model_validator(mode="after")
    def check_timeline(self):
        if self.scene_number > self.total:
            raise ValueError("Scene number must not exceed total")
        if self.cue_times and (self.cue_times != sorted(self.cue_times) or self.cue_times[0] < 0 or self.cue_times[-1] >= self.duration):
            raise ValueError("Cue times must be sorted and inside the scene duration")
        if self.cue_steps and (len(self.cue_steps) != len(self.cue_times) or self.cue_steps[0] != 0 or self.cue_steps != sorted(self.cue_steps)
                               or self.cue_steps[-1] >= visual_step_count(self.visual)):
            raise ValueError("Cue steps must start at zero, follow template order, and match the measured cues")
        return self


def allowed_kinds_without_graph():
    return {"bullets", "compare", "array", "equation"}


def visual_step_count(visual: VisualSpec):
    if visual.kind in TEXT_KINDS:
        return len(visual.items)
    if visual.kind == "compare":
        return 1 + len(visual.rows)
    if visual.kind == "array":
        return 1 + len(visual.pointers)
    if visual.kind == "code_trace":
        return 1 + len(visual.trace)
    if visual.kind == "plot":
        return 1 + 2 * len(visual.points) + int(visual.fit_line)
    return len(visual.nodes) + 2 * len(visual.edges)


class LegacyVisualSpec(VisualSpec):
    """The single-owner MVP renders with Manim, which draws only the original kinds."""
    kind: Literal["process", "cycle", "tree", "plot", "code_trace"]
