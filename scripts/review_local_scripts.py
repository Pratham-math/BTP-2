"""Explicit local text benchmark; save candidates for manual content review."""

import argparse
import json
import platform
import sys
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from dotenv import load_dotenv
    load_dotenv(root / ".env")
    from server.config import GenerationSettings, snapshot_settings
    from server.preflight import check_settings, require_ready
    from server.providers.ollama_text import OllamaTextProvider
    from server.runtime import CURRENT_CONTROL, JobControl
    from server.storage import atomic_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:4b-q4_K_M")
    parser.add_argument("--ids", nargs="*", help="Review just these prompt IDs (default: all twelve)")
    parser.add_argument("--output", type=Path, default=root / ".run" / "local-script-review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    settings = snapshot_settings(GenerationSettings(mode="local", text_model=args.model))
    require_ready(check_settings(settings, root / "data", probe=True))
    prompts = json.loads((root / "scripts" / "review_prompts.json").read_text(encoding="utf-8"))
    records = []
    for case in prompts:
        if args.ids and case["id"] not in args.ids:
            continue
        folder = args.output / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        control = JobControl(folder)
        token = CURRENT_CONTROL.set(control)
        provider = OllamaTextProvider(args.model, settings.text_identity)
        start = time.monotonic()
        record = {"id": case["id"], "expectation": case.get("expected_visual", case.get("expected_outcome")),
                  "manual_content_review": "pending"}
        try:
            script = provider.generate_script(case["prompt"], folder, lambda *_: None)
            atomic_json(folder / "script.json", script.model_dump())
            record.update(schema_valid=True, visuals=[scene.visual.kind for scene in script.scenes])
            record["expectation_met"] = all(scene.visual.kind == case["expected_visual"] for scene in script.scenes) if "expected_visual" in case else None
        except Exception as error:
            from server.generator import safe_error
            safe = safe_error(error, "scripting")
            record.update(schema_valid=False, error_code=safe.code, error=str(safe))
            record["expectation_met"] = safe.code == "UNSUPPORTED_REQUEST" if case.get("expected_outcome") in {"clarify-or-limit", "explain-template-limit"} else False
        finally:
            provider.close()
            CURRENT_CONTROL.reset(token)
        record["seconds"] = round(time.monotonic() - start, 2)
        candidates = list(folder.glob("candidate-*-attempt-*.json"))
        record["candidate_responses"] = len(candidates)
        record["units_with_repair"] = len(list(folder.glob("candidate-*-attempt-2.json")))
        records.append(record)
        report = {"host": platform.node(), "os": platform.platform(), "settings": settings.model_dump(),
                  "prompts": records, "factual_accuracy_established": False}
        atomic_json(args.output / "report.json", report)
        print(f'{case["id"]}: schema_valid={record["schema_valid"]}, {record["seconds"]}s', flush=True)


if __name__ == "__main__":
    main()
