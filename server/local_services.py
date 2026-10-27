"""Local-profile adapters: accounts, on-disk storage, Python runner, parsing.

Selected only by PLATFORM_PROFILE=local. Production keeps Supabase, R2 and Judge0.
The runner executes learner code on this machine, so it is refused elsewhere.
"""
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import jwt
from fastapi import HTTPException

from server.assessment.grading import matches
from server.auth import Actor
from server.config import PROJECT_DIR
from server.lessons.contracts import GradingKey
from server.providers.base import GenerationError

LOCAL_TEMP = PROJECT_DIR / ".local" / "tmp"


def is_local():
    return os.getenv("PLATFORM_PROFILE", "production").lower() == "local"


def local_secret():
    path = PROJECT_DIR / ".local" / "local-secret"
    if not path.exists():
        # Owner-only and exclusive, so concurrent API/worker starts cannot write different secrets.
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="ascii") as handle:
                handle.write(os.urandom(32).hex())
        except FileExistsError:
            pass
    return path.read_text(encoding="ascii").strip()


# Accounts ------------------------------------------------------------------

def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return salt.hex() + "$" + digest.hex()


def check_password(password: str, stored: str) -> bool:
    salt, _, expected = stored.partition("$")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).partition("$")[2], expected)


def issue_token(user_id, email, name, days=14):
    now = int(time.time())
    return jwt.encode({"sub": user_id, "email": email, "name": name, "iat": now, "exp": now + days * 86400, "aud": "btp2-local"},
                      local_secret(), algorithm="HS256")


def verify_local_token(token):
    try:
        claims = jwt.decode(token, local_secret(), algorithms=["HS256"], audience="btp2-local", options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Your session is invalid or expired. Sign in again.", headers={"WWW-Authenticate": "Bearer"}) from None
    return Actor(claims["sub"], claims.get("email", ""), claims.get("name", "Learner"))


# Storage -------------------------------------------------------------------

class LocalObjectStore:
    """Same interface as ObjectStore; files under data/objects, HMAC-signed URLs."""

    def __init__(self, root=None):
        self.root = Path(root or PROJECT_DIR / "data" / "objects").resolve()

    def path(self, key):
        from server.object_store import ObjectStore
        target = (self.root / ObjectStore.key(key)).resolve()
        if self.root not in target.parents:
            raise ValueError("Invalid private object key")
        return target

    def put(self, key, path, mime):
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.with_name(target.name + ".mime").write_text(mime, encoding="ascii")

    def download(self, key, path, limit):
        source = self.path(key)
        if not source.is_file():
            raise GenerationError("STORAGE_FAILED", "The stored source is missing.")
        if source.stat().st_size > limit:
            raise GenerationError("SOURCE_TOO_LARGE", "This source exceeds the configured upload size.")
        shutil.copyfile(source, path)

    @staticmethod
    def signature(key, expires):
        return hmac.new(local_secret().encode(), f"{key}|{expires}".encode(), hashlib.sha256).hexdigest()

    def sign(self, key, *, expires=300):
        until = int(time.time()) + expires
        return f"/api/local/objects/{self.path(key).relative_to(self.root).as_posix()}?expires={until}&signature={self.signature(key, until)}"

    def delete(self, key):
        target = self.path(key)
        target.unlink(missing_ok=True)
        target.with_name(target.name + ".mime").unlink(missing_ok=True)

    def list_prefix(self, prefix, *, limit=20000):
        folder = self.path(prefix.rstrip("/"))
        if not folder.is_dir():
            return []
        keys = [x.relative_to(self.root).as_posix() for x in folder.rglob("*") if x.is_file() and not x.name.endswith(".mime")]
        if len(keys) > limit:
            raise GenerationError("ERASURE_BATCH_REQUIRED", "The object inventory needs an operator-reviewed cleanup batch.")
        return keys

    def empty(self):
        return not self.root.exists() or not any(self.root.rglob("*"))


# Runner --------------------------------------------------------------------

def child_env():
    # No secrets, keys or user environment reach learner code.
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "PATH") if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", TEMP=str(LOCAL_TEMP), TMP=str(LOCAL_TEMP))
    return env


class LocalRunner:
    """Judge0-shaped runner: submit returns tokens, poll returns the graded result.

    ponytail: runs synchronously in submit; poll just reads the stored outcome.
    Not an isolation boundary. Use Judge0 on any shared host.
    """

    def __init__(self, settings=None):
        self.results = {}

    def ready(self):
        if not is_local():
            raise GenerationError("RUNNER_NOT_VERIFIED", "The local runner is only available in the local profile.")

    def run(self, code, stdin):
        LOCAL_TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=LOCAL_TEMP) as folder:
            script = Path(folder) / "main.py"
            script.write_text(code, encoding="utf-8")
            try:
                done = subprocess.run([sys.executable, "-I", "-S", str(script)], input=stdin.encode(), cwd=folder, env=child_env(),
                                      capture_output=True, timeout=5, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            except subprocess.TimeoutExpired:
                return False, ""
            # Windows text-mode stdout writes \r\n; graders and keys use \n.
            return done.returncode == 0, done.stdout[:65536].decode("utf-8", errors="replace").replace("\r\n", "\n")

    def submit(self, code, key):
        self.ready()
        grading = GradingKey.model_validate(key)
        if not isinstance(code, str) or not code.strip() or len(code) > 16000:
            raise GenerationError("INVALID_CODE", "Submit between 1 and 16000 characters of Python code.")
        outcomes = []
        for case in grading.tests:
            ok, output = self.run(code, case.stdin)
            outcomes.append({"passed": ok and matches(output, case.expected, grading.comparison, grading.tolerance),
                             "category": case.category, "essential": case.essential, "weight": case.weight})
        token = uuid.uuid4().hex
        self.results[token] = outcomes
        return [token] * len(grading.tests)

    def poll(self, tokens, key):
        outcomes = self.results.get(tokens[0]) if tokens else None
        if outcomes is None:  # Worker restarted between submit and poll: rerun is safe.
            raise GenerationError("RUNNER_FAILED", "The grading result was lost. Retry grading.")
        score = sum(x["weight"] for x in outcomes if x["passed"]) / sum(x["weight"] for x in outcomes)
        passed = score >= .8 and all(x["passed"] for x in outcomes if x["essential"])
        return {"passed": passed, "score": score, "feedback": "All required checks passed." if passed else "Some checks did not pass. Use a hint and review your code.",
                "failed_categories": sorted({x["category"] for x in outcomes if not x["passed"]})}

    def close(self):
        pass


# Parsing -------------------------------------------------------------------

def extract_locally(path: Path, kind: str, *, objects=None, prefix=None):
    """Run the existing parser in a separate interpreter with a time limit."""
    from server.lessons.contracts import EvidenceBlock
    LOCAL_TEMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=LOCAL_TEMP) as output:
        result_path = Path(output) / "extraction.json"
        env = child_env() | {"PYTHONPATH": str(PROJECT_DIR)}
        try:
            subprocess.run([sys.executable, "-m", "server.ingestion.local_parse", str(path), kind, str(result_path)], cwd=PROJECT_DIR,
                           env=env, timeout=180, check=False, capture_output=True,
                           **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        except subprocess.TimeoutExpired:
            raise GenerationError("PARSER_TIMEOUT", "Reading this document took too long. Split it into smaller files.") from None
        if not result_path.is_file():
            raise GenerationError("INVALID_EXTRACTION", "The document could not be read. Try exporting it again as PDF or PPTX.")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("error_code"):
            raise GenerationError(result["error_code"], result["message"])
        evidence = []
        for entry in result["evidence"]:
            name = entry.pop("preview_file", None)
            entry["image_key"] = None
            preview = Path(output) / name if name else None
            if objects is not None and prefix and preview and preview.is_file():
                key = f"{prefix}/{name}"
                objects.put(key, preview, "image/png")
                entry["image_key"] = key
            evidence.append(EvidenceBlock.model_validate(entry).model_dump())
        return evidence, result["warnings"]
