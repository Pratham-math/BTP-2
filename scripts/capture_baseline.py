"""Record hashes and versions of an existing ready job without private text."""

import json
from importlib.metadata import version
from pathlib import Path


def main():
    import sys
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from server.artifacts import file_hash
    from server.media import verify_video
    from server.storage import atomic_json
    records = []
    for path in sorted((root / "data").glob("*/status.json")):
        status = json.loads(path.read_text(encoding="utf-8"))
        if status.get("state") != "ready" or not (path.parent / "video.mp4").exists():
            continue
        files = [p for p in path.parent.iterdir() if p.suffix in {".wav", ".mp4"} or p.name == "script.json"]
        records.append({"id": status["id"], "files": {p.name: file_hash(p) for p in files},
                        "media": verify_video(path.parent / "video.mp4")})
    report = {"packages": {name: version(name) for name in ("fastapi", "google-genai", "manim", "Pillow", "pydantic")},
              "jobs": records, "live_narration_reviewed": False}
    atomic_json(root / ".run" / "baseline.json", report)
    print(f"Recorded {len(records)} existing ready jobs in .run/baseline.json; narration has not been reviewed.")


if __name__ == "__main__":
    main()
