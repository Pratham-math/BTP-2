"""Encrypted application-record/object backups. Auth and DB roles are NOT included.

Restore is deliberately limited to an empty migrated database and a different
private bucket. It never drops, truncates or overwrites existing database rows.
Keep the encryption key outside the backup; losing it makes recovery impossible.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import func, insert, select, update

from server.database import Base, make_engine
from server.object_store import ObjectStore
from server.platform_settings import PlatformSettings

MAGIC = b"BTP2-BACKUP-1\n"


def backup_key():
    key = bytes.fromhex(os.environ.get("BTP_BACKUP_KEY", ""))
    if len(key) != 32:
        raise ValueError("Set BTP_BACKUP_KEY to a 64-hex-character encryption key from your password manager.")
    return key


@contextmanager
def encrypted_writer(path, key):
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    with path.open("xb") as output:
        output.write(MAGIC + nonce)
        def write(value): output.write(encryptor.update(value))
        yield write
        output.write(encryptor.finalize())
        output.write(encryptor.tag)


def decrypt_to(path, destination, key):
    with path.open("rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise ValueError("Unsupported backup format")
        nonce = source.read(12)
        size = path.stat().st_size - len(MAGIC) - 12 - 16
        if size < 0:
            raise ValueError("Truncated encrypted backup")
        source.seek(-16, 2)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, source.read(16))).decryptor()
        decryptor.authenticate_additional_data(MAGIC)
        source.seek(len(MAGIC) + 12)
        with destination.open("xb") as output:
            os.chmod(destination, 0o600)
            remaining = size
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk: raise ValueError("Truncated encrypted backup")
                output.write(decryptor.update(chunk)); remaining -= len(chunk)
            output.write(decryptor.finalize())  # Authentication must pass before any restore.


def database_identity(engine):
    return hashlib.sha256(engine.url.render_as_string(hide_password=True).encode()).hexdigest()


def snapshot(engine, directory, key, settings, *, include_objects=False, objects=None):
    directory.mkdir(parents=True, exist_ok=False)
    refs, counts = {}, {}
    manifest = {"format": 1, "created_at": time.time(), "scope": "application-only", "database_identity": database_identity(engine),
                "auth_and_roles_included": False, "object_bytes_included": include_objects,
                "source_bucket": settings.s3_bucket, "source_endpoint": settings.s3_endpoint}
    connection = engine.connect()
    try:
        if engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        with connection.begin(), encrypted_writer(directory / "records.enc", key) as write:
            write((json.dumps({"manifest": manifest}) + "\n").encode())
            for table in Base.metadata.sorted_tables:
                counts[table.name] = 0
                for row in connection.execute(select(table)).mappings():
                    record = dict(row)
                    write((json.dumps({"table": table.name, "row": record}, allow_nan=False) + "\n").encode())
                    counts[table.name] += 1
                    object_key = record.get("object_key")
                    if object_key:
                        refs[ObjectStore.key(object_key)] = record.get("checksum")
                    if table.name == 'sources':
                        for preview_key in record.get('metadata_json', {}).get('preview_keys', []):
                            refs.setdefault(ObjectStore.key(preview_key), None)
            write((json.dumps({"objects": refs, "counts": counts}) + "\n").encode())
    finally:
        connection.close()
    if include_objects:
        objects = objects or ObjectStore(settings)
        (directory / "objects").mkdir()
        for object_key, expected in refs.items():
            with tempfile.TemporaryDirectory(prefix="btp-backup-object-") as folder:
                local = Path(folder) / "object"
                objects.download(object_key, local, 512 * 1024 * 1024)
                with local.open("rb") as stream: checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if expected and checksum != expected: raise ValueError("An object did not match its saved checksum")
                with encrypted_writer(directory / "objects" / (hashlib.sha256(object_key.encode()).hexdigest() + ".enc"), key) as write, local.open("rb") as source:
                    while chunk := source.read(1024 * 1024): write(chunk)
    (directory / "COMPLETE").write_text("application-only\n", encoding="utf-8")
    return {"tables": len(counts), "records": sum(counts.values()), "referenced_objects": len(refs), "object_bytes_included": include_objects}


def restore(engine, directory, key, settings, *, objects=None):
    if not (directory / "COMPLETE").is_file(): raise ValueError("The backup did not finish successfully")
    with tempfile.TemporaryDirectory(prefix="btp-restore-") as folder:
        plain = Path(folder) / "records.jsonl"
        decrypt_to(directory / "records.enc", plain, key)
        with plain.open(encoding="utf-8") as source:
            manifest = json.loads(next(source))["manifest"]
            summary = None
            for line in source:
                record = json.loads(line)
                if "objects" in record: summary = record
                elif record.get("table") not in Base.metadata.tables: raise ValueError("Unknown backup table")
        if manifest.get("format") != 1 or summary is None or set(summary["counts"]) != set(Base.metadata.tables):
            raise ValueError("Incomplete backup inventory")
        if manifest["database_identity"] == database_identity(engine): raise ValueError("Restore requires a different database")
        if not manifest["object_bytes_included"] and summary["objects"]: raise ValueError("This snapshot has object references only; use a backup including object bytes")
        with engine.begin() as connection:
            if any(connection.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables):
                raise ValueError("Restore requires an EMPTY migrated database; no existing records were modified")
            if summary["objects"]:
                if (settings.s3_bucket, settings.s3_endpoint) == (manifest["source_bucket"], manifest["source_endpoint"]):
                    raise ValueError("Restore requires a different private bucket")
                objects = objects or ObjectStore(settings)
                if not objects.empty(): raise ValueError("Restore requires an EMPTY private bucket")
                for object_key, expected in summary["objects"].items():
                    local = Path(folder) / "object"
                    if local.exists(): local.unlink()
                    filename = hashlib.sha256(object_key.encode()).hexdigest() + ".enc"
                    decrypt_to(directory / "objects" / filename, local, key)
                    with local.open("rb") as stream: checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                    if expected and checksum != expected: raise ValueError("Restored object checksum mismatch")
                    mime = ("text/vtt" if object_key.endswith(".vtt") else "video/mp4" if object_key.endswith(".mp4")
                        else "image/png" if object_key.endswith('.png') else "image/jpeg" if object_key.endswith(('.jpg', '.jpeg'))
                        else "application/pdf" if object_key.endswith('.pdf') else "application/octet-stream")
                    objects.put(ObjectStore.key(object_key), local, mime)
            blocks, versions, counts = [], [], {name: 0 for name in summary["counts"]}
            with plain.open(encoding="utf-8") as source:
                next(source)
                for line in source:
                    item = json.loads(line)
                    if "table" not in item: continue
                    name, row = item["table"], item["row"]
                    if name == "curricula" and row["publication"] != "draft":
                        versions.append((row["id"], row["publication"])); row["publication"] = "draft"
                    if name == "blocks" and row["state"] == "ready":
                        blocks.append(row["id"]); row["state"] = "rendering"
                    if name == "jobs" and row["state"] in {"queued", "running"}:
                        row.update(state="waiting_for_input", error_code="RESTORED_REVIEW_REQUIRED", lease_until=None, fence=row["fence"] + 1)
                    if name == "attempts" and row["state"] in {"submitted", "running"}:
                        row.update(state="service_failed", result={"feedback": "Restored saved code. Retry grading when the runner is verified."})
                    if name == "learning_sessions" and row["state"] == "submitting": row["state"] = "checkpoint"
                    connection.execute(insert(Base.metadata.tables[name]).values(**row)); counts[name] += 1
            if counts != summary["counts"]: raise ValueError("Backup record counts do not match")
            for identifier in blocks:
                connection.execute(update(Base.metadata.tables["blocks"]).where(Base.metadata.tables["blocks"].c.id == identifier).values(state="ready"))
            for identifier, publication in versions:
                connection.execute(update(Base.metadata.tables["curricula"]).where(Base.metadata.tables["curricula"].c.id == identifier).values(publication=publication))
        return {"records": sum(counts.values()), "objects": len(summary["objects"]), "auth_restoration_still_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "restore"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--include-objects", action="store_true")
    parser.add_argument("--confirm-empty-restore-target", action="store_true")
    args = parser.parse_args()
    settings = PlatformSettings.from_env()
    if args.action == "restore" and not args.confirm_empty_restore_target: parser.error("Explicit --confirm-empty-restore-target is required")
    engine = make_engine(settings.database_url)
    try:
        result = snapshot(engine, args.directory, backup_key(), settings, include_objects=args.include_objects) if args.action == "snapshot" else restore(engine, args.directory, backup_key(), settings)
        print(json.dumps({"scope": "application-only", **result}))
    except Exception as error:
        # DB and SDK exceptions can contain secret URLs or private content.
        print(json.dumps({"failed": True, "error_type": type(error).__name__, "action": "Check the key, fresh destination, service access and operator runbook. Partial backup folders have no COMPLETE marker."}))
        return 1
    finally: engine.dispose()
    return 0


if __name__ == "__main__": raise SystemExit(main())
