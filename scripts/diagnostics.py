"""Print a bounded runtime report without secrets, prompts, or job contents."""

import json
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from dotenv import load_dotenv
    load_dotenv(root / ".env")
    from importlib.metadata import PackageNotFoundError, version
    from server.preflight import provider_inventory
    from server.runtime import run_command
    from server.config import PROFILES
    packages = {}
    for name in ("fastapi", "google-genai", "manim", "Pillow", "pydantic", "piper-tts", "onnxruntime"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    executables = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            executables[name] = run_command([name, "-version"], timeout=10).stdout.splitlines()[0]
        except RuntimeError:
            executables[name] = "not available"
    print(json.dumps({"python": sys.version.split()[0], "packages": packages, "media_tools": executables,
                      "profiles": PROFILES, "providers": provider_inventory()}, indent=2))


if __name__ == "__main__":
    main()
