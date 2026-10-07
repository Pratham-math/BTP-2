"""Render validated data using fixed Manim templates, in a separate process.

No generated code, network requests, LaTeX, or external assets are evaluated.
"""

import math
import sys
import tempfile
from pathlib import Path
from textwrap import fill

import numpy as np
from manim import (
    Arrow, Axes, Circle, Create, CurvedArrow, Dot, Ellipse, FadeIn,
    GrowArrow, Indicate, Line, MoveAlongPath, Rectangle,
    Scene, Text, Union, VGroup, VMobject, config, linear, tempconfig,
)

from server.visuals import RenderRequest, VisualSpec
from server.config import PROFILES


PAPER = "#F4F1E9"
INK = "#272421"
MUTED = "#716B62"
COLORS = {"teal": "#28786F", "blue": "#326C9B", "amber": "#AD7519", "red": "#AE4545", "ink": INK}


def label(text: str, width: float, height: float, size: int = 26, color: str = INK):
    item = Text(text, font="Arial", font_size=size, color=color, disable_ligatures=True)
    if item.width > width:
        item.scale_to_fit_width(width)
    if item.height > height:
        item.scale_to_fit_height(height)
    return item


def icon(kind: str, color: str):
    if kind == "sun":
        rays = VGroup(*[
            Line(
                [math.cos(a) * .42, math.sin(a) * .42, 0],
                [math.cos(a) * .61, math.sin(a) * .61, 0], color=color, stroke_width=3,
            ) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)
        ])
        return VGroup(Circle(radius=.3, color=color, fill_opacity=.2), rays)
    if kind == "plant":
        return VGroup(
            Line([0, -.5, 0], [0, .5, 0], color=color, stroke_width=4),
            Ellipse(width=.65, height=.3, color=color, fill_opacity=.35).rotate(.55).move_to([.27, .2, 0]),
            Ellipse(width=.65, height=.3, color=color, fill_opacity=.35).rotate(-.55).move_to([-.27, -.1, 0]),
            Line([-.4, -.5, 0], [.4, -.5, 0], color=color, stroke_width=3),
        )
    if kind == "water":
        drop = VMobject(color=color, fill_opacity=.25)
        drop.start_new_path(np.array([0, .55, 0]))
        drop.add_cubic_bezier_curve_to(np.array([-.15, .25, 0]), np.array([-.38, -.02, 0]), np.array([-.32, -.22, 0]))
        drop.add_cubic_bezier_curve_to(np.array([-.25, -.6, 0]), np.array([.25, -.6, 0]), np.array([.32, -.22, 0]))
        drop.add_cubic_bezier_curve_to(np.array([.38, -.02, 0]), np.array([.15, .25, 0]), np.array([0, .55, 0]))
        return drop
    if kind == "cloud":
        circles = [
            Circle(radius=r).move_to([x, y, 0])
            for x, y, r in [(-.34, -.1, .27), (0, .1, .36), (.34, -.1, .27)]
        ]
        return Union(*circles, color=color, fill_color=PAPER, fill_opacity=1)
    if kind == "computer":
        return VGroup(
            Rectangle(width=1, height=.65, color=color),
            Line([0, -.33, 0], [0, -.55, 0], color=color),
            Line([-.32, -.55, 0], [.32, -.55, 0], color=color),
        )
    return Circle(radius=.3, color=color)


def node_object(node, tree=False):
    color = COLORS[node.color]
    if tree:
        body = Circle(radius=.43, color=color, fill_color=color, fill_opacity=.12)
        text = label(fill(node.label, 11), 1.9, .58, size=22)
        if len(node.label) <= 5:
            text.move_to(body)
        else:
            text.next_to(body, [0, -1, 0], buff=.1)
        return VGroup(body, text)
    if node.icon != "none":
        picture = icon(node.icon, color).scale(.8)
        text = label(fill(node.label, 16), 2.1, .65, size=24)
        text.next_to(picture, [0, -1, 0], buff=.18)
        return VGroup(picture, text)
    box = Rectangle(width=2.15, height=1.0, color=color, fill_color=color, fill_opacity=.07)
    text = label(fill(node.label, 16), 1.9, .73, size=24).move_to(box)
    return VGroup(box, text)


def diagram_positions(visual: VisualSpec):
    ids = [node.id for node in visual.nodes]
    if visual.kind == "process":
        if len(ids) <= 3:
            return {key: np.array([x, 0, 0]) for key, x in zip(ids, np.linspace(-3.8, 3.8, len(ids)))}
        slots = [(-4, 1.2), (0, 1.2), (4, 1.2), (4, -1.2), (0, -1.2), (-4, -1.2)]
        return {key: np.array([x, y, 0]) for key, (x, y) in zip(ids, slots)}
    if visual.kind == "cycle":
        return {key: np.array([4.4 * math.cos(a), 1.55 * math.sin(a), 0])
                for key, a in zip(ids, np.linspace(math.pi / 2, math.pi / 2 - 2 * math.pi, len(ids), endpoint=False))}

    children = {key: [] for key in ids}
    for edge in visual.edges:
        children[edge.source].append(edge.target)
    root = next(key for key in ids if key not in {edge.target for edge in visual.edges})
    positions = {}
    leaves = []

    def place(key, depth):
        xs = [place(child, depth + 1) for child in children[key]]
        x = sum(xs) / len(xs) if xs else float(len(leaves))
        if not xs:
            leaves.append(key)
        positions[key] = (x, depth)
        return x

    place(root, 0)
    max_depth = max(depth for _, depth in positions.values())
    return {key: np.array([
        (x / (len(leaves) - 1) - .5) * 9.8 if len(leaves) > 1 else 0,
        1.65 - depth * 3.3 / max_depth, 0,
    ]) for key, (x, depth) in positions.items()}


class LessonAnimation(Scene):
    def __init__(self, request: RenderRequest, **kwargs):
        self.request = request
        super().__init__(**kwargs)

    def construct(self):
        request = self.request
        self.camera.background_color = PAPER
        title = label(request.title, 11.6, .8, size=36).move_to([-6.25, 3.2, 0], aligned_edge=[-1, 0, 0])
        number = label(f"{request.scene_number:02d} / {request.total:02d}", 1, .3, size=18, color=MUTED).move_to([6, 3.2, 0])
        caption = label(fill(request.visual.caption, 83), 12.1, .75, size=24).move_to([0, -3.2, 0])
        self.add(title, number, caption,
                 Line([-6.3, 2.65, 0], [6.3, 2.65, 0], color=MUTED, stroke_width=1),
                 Line([-6.3, -2.65, 0], [6.3, -2.65, 0], color=MUTED, stroke_width=1))

        steps = self.plot_steps() if request.visual.kind == "plot" else self.diagram_steps()
        # Every action gets a share of the actual WAV duration. Reserving a
        # final hold keeps the completed diagram visible and absorbs rounding.
        total_frames = max(len(steps) + 1, round(request.duration * config.frame_rate))
        active_frames = max(len(steps), round(total_frames * .9))
        for index, animations in enumerate(steps):
            frames = active_frames // len(steps) + (index < active_frames % len(steps))
            # Manim samples np.arange(0, duration, frame_interval). Floating-point
            # endpoints can add one frame per play. Stay just inside the endpoint
            # while preserving at least one complete frame for tiny previews.
            run_time = (frames - 1e-6) / config.frame_rate if frames > 1 else 1 / config.frame_rate
            self.play(*animations, run_time=run_time)
        hold_frames = max(1, total_frames - active_frames)
        self.wait((hold_frames - 1e-6) / config.frame_rate if hold_frames > 1 else 1 / config.frame_rate)

    def diagram_steps(self):
        visual = self.request.visual
        positions = diagram_positions(visual)
        objects = {node.id: node_object(node, visual.kind == "tree").move_to(positions[node.id]) for node in visual.nodes}
        steps = [[FadeIn(objects[node.id])] for node in visual.nodes]
        arrows = []
        for edge in visual.edges:
            source, target = objects[edge.source], objects[edge.target]
            delta = target.get_center() - source.get_center()
            start = source.get_critical_point(delta) + delta / np.linalg.norm(delta) * .12
            end = target.get_critical_point(-delta) - delta / np.linalg.norm(delta) * .12
            if visual.kind == "cycle":
                arrow = CurvedArrow(start, end, angle=-.5, color=MUTED, stroke_width=2.5, tip_length=.14)
                steps.append([Create(arrow)])
            else:
                arrow = Arrow(start, end, buff=0, color=MUTED, stroke_width=2.5, max_tip_length_to_length_ratio=.12)
                steps.append([GrowArrow(arrow)])
            arrows.append((arrow, target))
        # A marker travels through the diagram, then the destination is
        # emphasized. These are real moving frames, not a still-image zoom.
        for arrow, target in arrows:
            marker = Dot(arrow.get_start(), radius=.065, color=COLORS["amber"])
            steps.append([MoveAlongPath(marker, arrow, rate_func=linear, remover=True),
                          Indicate(target, color=COLORS["amber"], scale_factor=1.05)])
        return steps

    def plot_steps(self):
        visual = self.request.visual
        xs = np.array([point.x for point in visual.points])
        ys = np.array([point.y for point in visual.points])
        x_span = max(float(np.ptp(xs)), 1)
        y_span = max(float(np.ptp(ys)), 1)
        x_low, x_high = float(xs.min() - .15 * x_span), float(xs.max() + .15 * x_span)
        y_low, y_high = float(ys.min() - .15 * y_span), float(ys.max() + .15 * y_span)
        axes = Axes(x_range=[x_low, x_high, (x_high - x_low) / 4],
                    y_range=[y_low, y_high, (y_high - y_low) / 4],
                    x_length=9, y_length=3.8, tips=False,
                    axis_config={"color": MUTED, "include_ticks": False, "include_numbers": False})
        axes.move_to([.25, .1, 0])
        labels = VGroup(label(visual.x_label, 4, .35, size=20).move_to([.25, -2.3, 0]),
                        label(visual.y_label, 3.5, .35, size=20).rotate(math.pi / 2).move_to([-5.65, .1, 0]))
        for value in np.linspace(x_low, x_high, 5):
            labels.add(label(f"{value:.2g}", .8, .22, size=15).move_to(axes.c2p(value, y_low) + [0, -.2, 0]))
        for value in np.linspace(y_low, y_high, 5):
            labels.add(label(f"{value:.2g}", .75, .22, size=15).move_to(axes.c2p(x_low, value) + [-.48, 0, 0]))
        dots = [Dot(axes.c2p(x, y), radius=.075, color=COLORS["blue"]) for x, y in zip(xs, ys)]
        steps = [[Create(axes), FadeIn(labels)]] + [[FadeIn(dot)] for dot in dots]
        if visual.fit_line:
            slope = float(np.sum((xs - xs.mean()) * (ys - ys.mean())) / np.sum((xs - xs.mean()) ** 2))
            intercept = float(ys.mean() - slope * xs.mean())
            # Clip the line to the visible plot rectangle.
            left, right = x_low, x_high
            if abs(slope) > 1e-12:
                crossings = sorted(((y_low - intercept) / slope, (y_high - intercept) / slope))
                left, right = max(left, crossings[0]), min(right, crossings[1])
            fit = Line(axes.c2p(left, slope * left + intercept), axes.c2p(right, slope * right + intercept), color=COLORS["red"], stroke_width=3)
            steps.append([Create(fit)])
            for x, y, dot in zip(xs, ys, dots):
                residual = Line(axes.c2p(x, y), axes.c2p(x, slope * x + intercept), color=COLORS["amber"], stroke_width=2)
                steps.append([Create(residual), Indicate(dot, color=COLORS["amber"])])
        else:
            steps.extend([[Indicate(dot, color=COLORS["amber"])] for dot in dots])
        return steps


def render(request: RenderRequest, output_path: Path):
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height, fps = PROFILES[request.render_profile]
    with tempfile.TemporaryDirectory(prefix="manim-", dir=output_path.parent) as media_dir:
        with tempconfig({
            "renderer": "cairo", "pixel_width": width, "pixel_height": height,
            "frame_rate": fps, "frame_width": 128 / 9, "frame_height": 8,
            "media_dir": media_dir, "video_dir": media_dir,
            "output_file": "animation", "format": "mp4",
            "write_to_movie": True, "save_last_frame": False,
            "preview": False, "disable_caching": True,
            "verbosity": "ERROR", "progress_bar": "none",
        }):
            scene = LessonAnimation(request)
            scene.render()
            Path(scene.renderer.file_writer.movie_file_path).replace(output_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m server.manim_renderer <scene.json> <output.mp4>")
    render(RenderRequest.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8")), Path(sys.argv[2]))
