"""Content-addressed reuse of verified files inside a single job directory."""

import hashlib
import json
import re
from pathlib import Path

from server.providers.base import GenerationError
from server.storage import atomic_json


def input_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ArtifactStore:
    def __init__(self, folder: Path):
        self.folder = folder.resolve()
        self.manifest = self.folder / "manifest.json"

    def _read(self) -> dict:
        if not self.manifest.exists():
            return {"schema_version": 2, "artifacts": {}}
        try:
            if self.manifest.is_symlink():
                raise ValueError("Manifest must stay inside job storage")
            data = json.loads(self.manifest.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 2 or not isinstance(data.get("artifacts"), dict):
                raise ValueError("Unsupported manifest")
            for key, record in data["artifacts"].items():
                if not isinstance(key, str) or not isinstance(record, dict):
                    raise ValueError("Invalid artifact record")
                name = record.get("path")
                if not isinstance(name, str) or not name or Path(name).name != name:
                    raise ValueError("Invalid artifact filename")
                if any(not isinstance(record.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", record[field])
                       for field in ("input_hash", "checksum")):
                    raise ValueError("Invalid artifact checksum")
                if not isinstance(record.get("metadata", {}), dict):
                    raise ValueError("Invalid artifact metadata")
            return data
        except (ValueError, OSError) as error:
            raise GenerationError("STORAGE_CORRUPT", "The saved artifact manifest is damaged; it has been preserved.",
                                  "Start a new job or restore the manifest from a backup.") from error

    def _path(self, name: str) -> Path:
        original = self.folder / name
        path = original.resolve()
        if path.parent != self.folder or original.is_symlink():
            raise GenerationError("INVALID_ARTIFACT", "An artifact path is outside its job directory.")
        return path

    def reusable(self, key: str, inputs, path: Path) -> dict | None:
        record = self._read()["artifacts"].get(key)
        if not record or record.get("input_hash") != input_hash(inputs) or record.get("path") != path.name:
            return None
        try:
            checked = self._path(path.name)
            if checked.is_file() and file_hash(checked) == record.get("checksum"):
                return record
        except OSError:
            pass
        return None

    def record(self, key: str, inputs, path: Path, metadata: dict | None = None):
        checked = self._path(path.name)
        data = self._read()
        data["artifacts"][key] = {"path": path.name, "input_hash": input_hash(inputs),
                                  "checksum": file_hash(checked), "metadata": metadata or {}}
        atomic_json(self.manifest, data)

    def publish(self, **metadata):
        data = self._read()
        data.update(metadata)
        atomic_json(self.manifest, data)
