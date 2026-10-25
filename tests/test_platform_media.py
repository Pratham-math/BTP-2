"""Actual code-trace/semantic rendering with explicitly synthetic fixture audio."""
import math
import wave
from pathlib import Path

from server.lessons.contracts import InstructionScene
from server.media import mux_animation, render_animation, verify_video


def test_semantic_code_trace_renders_without_executing_displayed_python(tmp_path):
    scene = InstructionScene(id="trace", title="Follow the displayed code", bullets=["Display data only"],
        utterances=[{"text": "First inspect the code and its initial state.", "visual_step": 0},
                    {"text": "Then follow the highlighted line as the state changes.", "visual_step": 2}],
        visual={"kind": "code_trace", "caption": "The code is rendered as text and is never executed.",
                "code_lines": ["raise RuntimeError('Never execute this')", "total = 0", "total += 2"],
                "trace": [{"line": 2, "variables": {"total": "0"}}, {"line": 3, "variables": {"total": "2"}, "array": ["2", "3"], "active_index": 0}]})
    audio = tmp_path / "fixture.wav"
    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
        out.writeframes(b"".join(int(1800 * math.sin(2 * math.pi * 330 * i / 24000)).to_bytes(2, "little", signed=True) for i in range(96000)))
    silent, clip = tmp_path / "trace.silent.mp4", tmp_path / "trace.mp4"
    render_animation(scene, 4.5, silent, 4, 8, "480p24", cue_times=[.15, 2.15], cue_steps=[0, 2])
    mux_animation(silent, audio, clip, "480p24", .15, .35)
    info = verify_video(clip, expected_duration=4.5, decode=True)
    assert len(info["streams"]) == 2
