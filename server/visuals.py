"""Bounded scene data shared by Gemini validation and the local Manim renderer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class VisualSpec(VisualModel):
    kind: Literal["process", "cycle", "tree", "plot"]
    caption: str = Field(min_length=1, max_length=110)
    nodes: list[VisualNode] = Field(default_factory=list, max_length=7)
    edges: list[VisualEdge] = Field(default_factory=list, max_length=8)
    points: list[PlotPoint] = Field(default_factory=list, max_length=12)
    x_label: str = Field(default="", max_length=24)
    y_label: str = Field(default="", max_length=24)
    fit_line: bool = False

    @model_validator(mode="after")
    def check_diagram(self):
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
    scene_number: int = Field(ge=1, le=3)
    total: int = Field(ge=1, le=3)
