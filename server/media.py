"""Trusted Pillow/Manim rendering and FFmpeg export helpers."""

import json
import math
import os
import sys
import wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from server.script import Scene
from server.visuals import RenderRequest
from server.runtime import run_command
from server.config import PROFILES
from server.providers.base import GenerationError, inspect_audio
from server.storage import atomic_json


def draw_slide(scene: Scene, output_path: Path, scene_number: int, total: int) -> None:
    image = Image.new("RGB", (1280, 720), "#08111f")
    draw = ImageDraw.Draw(image)
    title_font = load_font(52, bold=True)
    bullet_font = load_font(32)
    small_font = load_font(21)

    draw.rounded_rectangle((64, 58, 1216, 662), radius=28, fill="#111d30", outline="#273a55", width=2)
    draw.rounded_rectangle((96, 92, 176, 100), radius=4, fill="#66e3c4")
    title_lines = wrap_by_width(draw, scene.title, title_font, 1030)
    if len(title_lines) > 2:
        raise ValueError(f"Title overflows in scene {scene_number}")
    title_y = 130
    for line in title_lines:
        draw.text((96, title_y), line, font=title_font, fill="#f4f8ff")
        title_y += 62

    y = max(250, title_y + 36)
    for bullet in scene.bullets:
        lines = wrap_by_width(draw, bullet, bullet_font, 930)
        if y + len(lines) * 48 > 590:
            raise ValueError(f"Slide text overflows in scene {scene_number}")
        draw.ellipse((104, y + 13, 118, y + 27), fill="#66e3c4")
        for line in lines:
            draw.text((144, y), line, font=bullet_font, fill="#cbd7e8")
            y += 48
        y += 20

    draw.text((96, 615), "LEARN • VISUALIZE • REMEMBER", font=small_font, fill="#7589a5")
    label = f"{scene_number:02d} / {total:02d}"
    label_width = draw.textlength(label, font=small_font)
    draw.text((1178 - label_width, 615), label, font=small_font, fill="#66e3c4")

    temp_path = output_path.with_suffix(".tmp.png")
    image.save(temp_path, "PNG")
    os.replace(temp_path, output_path)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "arialbd.ttf" if bold else "arial.ttf"
    candidates = [
        Path("C:/Windows/Fonts") / filename,
        Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def wrap_by_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def make_scene_video(image_path: Path, audio_path: Path, output_path: Path,
                     profile: str = "720p24", lead_in: float = 0, tail: float = .25) -> None:
    duration = wav_duration(audio_path) + lead_in + tail
    width, height, fps = PROFILES[profile]
    temp_path = output_path.with_suffix(".tmp.mp4")
    run_command([
        "ffmpeg", "-y", "-loglevel", "error", "-threads", "2",
        "-loop", "1", "-framerate", str(fps), "-i", str(image_path), "-i", str(audio_path),
        "-vf", f"scale={width}:{height},setsar=1", "-c:v", "libx264", "-threads", "2",
        "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-ar", "48000", "-ac", "1",
        "-af", f"adelay={round(lead_in * 1000)}:all=1,apad=pad_dur={tail}",
        "-t", f"{duration:.3f}", "-movflags", "+faststart", str(temp_path),
    ], timeout=180)
    verify_video(temp_path, expected_duration=duration)
    os.replace(temp_path, output_path)


def render_animation(scene: Scene, duration: float, output_path: Path, scene_number: int,
                     total: int, profile: str = "720p24", *, cue_times: list[float] | None = None, cue_steps: list[int] | None = None):
    if scene.visual is None:
        raise ValueError("An animated scene needs a visual plan")
    request = RenderRequest(title=scene.title, visual=scene.visual, duration=duration,
                            scene_number=scene_number, total=total, render_profile=profile, cue_times=cue_times or [], cue_steps=cue_steps or [])
    plan_path = output_path.with_suffix(".json")
    atomic_json(plan_path, request.model_dump())
    render_env = {key: value for key, value in os.environ.items()
                  if not any(secret in key.upper() for secret in ("KEY", "TOKEN", "SECRET", "PASSWORD", "DATABASE_URL"))}
    render_env.update(PYTHONIOENCODING="utf-8", OMP_NUM_THREADS="2")
    temporary = output_path.with_suffix(".tmp.mp4")
    try:
        run_command([sys.executable, "-m", "server.manim_renderer", str(plan_path.resolve()), str(temporary.resolve())],
                    cwd=Path(__file__).resolve().parents[1], timeout=600, env=render_env)
        verify_video(temporary, require_audio=False, expected_duration=duration)
        os.replace(temporary, output_path)
    except GenerationError as error:
        if error.code in {"CANCELLED", "DISK_FULL", "JOB_TIMEOUT"}:
            raise
        raise GenerationError("RENDER_FAILED", "Animation rendering failed. Completed narration is saved.",
                              "Check Manim and retry rendering.") from error


def mux_animation(silent_path: Path, audio_path: Path, output_path: Path,
                  profile: str = "720p24", lead_in: float = 0, tail: float = .25):
    duration = wav_duration(audio_path) + lead_in + tail
    width, height, fps = PROFILES[profile]
    temp_path = output_path.with_suffix(".tmp.mp4")
    run_command([
        "ffmpeg", "-y", "-loglevel", "error", "-threads", "2",
        "-i", str(silent_path), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
        "-vf", f"scale={width}:{height},setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration=1",
        "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-ar", "48000", "-ac", "1",
        "-af", f"adelay={round(lead_in * 1000)}:all=1,apad=pad_dur={tail}",
        "-t", f"{duration:.3f}", "-movflags", "+faststart", str(temp_path),
    ], timeout=180)
    verify_video(temp_path, expected_duration=duration)
    os.replace(temp_path, output_path)


def make_animated_scene(scene: Scene, audio_path: Path, output_path: Path, scene_number: int,
                        total: int, profile: str = "720p24", lead_in: float = 0, tail: float = .25) -> None:
    silent = output_path.with_suffix(".silent.mp4")
    render_animation(scene, wav_duration(audio_path) + lead_in + tail, silent, scene_number, total, profile)
    mux_animation(silent, audio_path, output_path, profile, lead_in, tail)


def combine_videos(scene_paths: list[Path], output_path: Path) -> None:
    import re
    if not scene_paths or any(path.parent.resolve() != output_path.parent.resolve()
                              or not re.fullmatch(r"scene-[1-3]\.mp4", path.name) for path in scene_paths):
        raise ValueError("Concatenation uses only trusted scene files in the output directory")
    durations = [float(verify_video(path)["format"]["duration"]) for path in scene_paths]
    concat_path = output_path.parent / "concat.txt"
    concat_path.write_text("".join(f"file '{path.name}'\n" for path in scene_paths), encoding="utf-8")
    temp_path = output_path.with_suffix(".tmp.mp4")
    run_command(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "1",
                 "-i", concat_path.name, "-c", "copy", "-movflags", "+faststart", temp_path.name],
                cwd=output_path.parent, timeout=180)
    verify_video(temp_path, expected_duration=sum(durations), decode=True)
    os.replace(temp_path, output_path)


def verify_video(path: Path, require_audio: bool = True, expected_duration: float | None = None,
                 decode: bool = False) -> dict:
    if path.is_symlink():
        raise GenerationError("INVALID_ARTIFACT", "A video artifact cannot be a symbolic link.")
    result = run_command(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,codec_name,width,height,pix_fmt,sample_rate,channels,r_frame_rate",
                          "-of", "json", str(path)], timeout=30)
    try:
        details = json.loads(result.stdout)
        duration = float(details.get("format", {}).get("duration", 0))
    except (ValueError, TypeError) as error:
        raise GenerationError("INVALID_MEDIA", "Video verification returned invalid metadata.") from error
    stream_types = {stream.get("codec_type") for stream in details.get("streams", [])}
    if not path.exists() or path.stat().st_size == 0 or not math.isfinite(duration) or duration <= 0:
        raise GenerationError("INVALID_MEDIA", "The video output is empty or has an invalid duration.")
    if "video" not in stream_types or (require_audio and "audio" not in stream_types):
        raise GenerationError("INVALID_MEDIA", "The video is missing a required picture or narration stream.")
    video = next(stream for stream in details["streams"] if stream.get("codec_type") == "video")
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise GenerationError("INVALID_MEDIA", "The video does not match the browser-compatible H.264 export profile.")
    if require_audio:
        audio = next(stream for stream in details["streams"] if stream.get("codec_type") == "audio")
        if audio.get("codec_name") != "aac" or audio.get("sample_rate") != "48000" or audio.get("channels") != 1:
            raise GenerationError("INVALID_MEDIA", "The narration does not match the AAC export profile.")
    if expected_duration is not None and abs(duration - expected_duration) > .25:
        raise GenerationError("TIMING_MISMATCH", "Video duration does not match its complete narration timeline.")
    if decode:
        run_command(["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", str(path),
                     "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], timeout=180)
    return details


def wav_duration(path: Path) -> float:
    return inspect_audio(path).duration
