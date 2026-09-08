import json
import subprocess
import sys
from pathlib import Path


def inspect(path: Path) -> None:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    details = json.loads(result.stdout)
    streams = details.get("streams", [])
    kinds = {stream.get("codec_type") for stream in streams}
    duration = float(details.get("format", {}).get("duration", 0))
    if path.stat().st_size == 0 or duration <= 0 or not {"audio", "video"}.issubset(kinds):
        raise SystemExit(f"FAIL: {path} is not a playable audio/video file")
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    audio = next(stream for stream in streams if stream.get("codec_type") == "audio")
    if video.get("codec_name") != "h264" or (video.get("width"), video.get("height")) != (1280, 720):
        raise SystemExit(f"FAIL: {path} is not 1280x720 H.264")
    if audio.get("codec_name") != "aac":
        raise SystemExit(f"FAIL: {path} audio is not AAC")
    codecs = ", ".join(stream.get("codec_name", "unknown") for stream in streams)
    print(f"OK: {path} | {duration:.2f}s | {codecs}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_media.py <video.mp4>")
    inspect(Path(sys.argv[1]).resolve())
