"""Run document conversion without networking or application credentials."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from server.providers.base import GenerationError
from server.runtime import run_command


def extract_in_sandbox(path: Path, kind: str, *, objects=None, prefix=None):
    if os.getenv("DOCUMENT_SANDBOX_VERIFIED", "false").lower() != "true" or not shutil.which("docker"):
        raise GenerationError("PARSER_NOT_VERIFIED", "Build and verify the credential-free document sandbox, then set DOCUMENT_SANDBOX_VERIFIED=true. Corrected text notes remain available.")
    image = os.getenv("DOCUMENT_PARSER_IMAGE", "btp2-parser:local")
    # Image names are operator configuration, not source/model-provided commands.
    name = "btp2-parser-" + uuid4().hex
    env = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "DOCKER_HOST", "DOCKER_CONTEXT", "USERPROFILE"}}
    with tempfile.TemporaryDirectory(prefix="btp2-parsed-") as output:
        command = ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "2g", "--cpus", "1", "--pids-limit", "64",
            "--ulimit", "fsize=67108864", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m,mode=1777",
            "--mount", f"type=bind,source={path.resolve()},target=/input/source{path.suffix},readonly",
            "--mount", f"type=bind,source={Path(output).resolve()},target=/output", image,
            f"/input/source{path.suffix}", kind, "/output/extraction.json"]
        try:
            run_command(command, timeout=180, env=env)
            result_path = Path(output) / "extraction.json"
            if not result_path.is_file() or result_path.stat().st_size > 10 * 1024 * 1024:
                raise GenerationError("INVALID_EXTRACTION", "The document sandbox returned no bounded extraction result.")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("error_code"):
                raise GenerationError(result["error_code"], result["message"])
            # The container output is untrusted. Only exact generated page names
            # may be uploaded; never follow a parser-supplied path or object key.
            import re
            from server.lessons.contracts import EvidenceBlock
            previews = result.get('previews', [])
            names = {item['file'] for item in previews}
            if len(previews) > 200 or any(not re.fullmatch(r'page-[1-9][0-9]{0,2}\.png', name) for name in names):
                raise GenerationError('INVALID_EXTRACTION', 'The parser returned an invalid preview manifest.')
            mapped = {}
            if objects is not None and prefix:
                for name in sorted(names):
                    preview = Path(output) / name
                    if preview.is_symlink() or not preview.is_file() or preview.stat().st_size > 16 * 1024 * 1024:
                        raise GenerationError('INVALID_EXTRACTION', 'The parser returned an unsafe page preview.')
                    with preview.open('rb') as stream:
                        if stream.read(8) != b'\x89PNG\r\n\x1a\n':
                            raise GenerationError('INVALID_EXTRACTION', 'A page preview has an invalid signature.')
                    key = prefix + '/' + name
                    objects.put(key, preview, 'image/png')
                    mapped[name] = key
            evidence = []
            for entry in result['evidence']:
                entry = dict(entry)
                name = entry.pop('preview_file', None)
                entry['image_key'] = mapped.get(name)
                evidence.append(EvidenceBlock.model_validate(entry).model_dump())
            return evidence, result["warnings"]
        finally:
            # Cleanup must still work after the generation cancellation flag is
            # set. The exact owned random name can never target another runtime.
            subprocess.run(["docker", "rm", "--force", name], env=env, shell=False, timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
