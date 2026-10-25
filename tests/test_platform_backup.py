import os
import hashlib

from cryptography.exceptions import InvalidTag
import pytest
from sqlalchemy import select

from scripts.platform_backup import decrypt_to, encrypted_writer, restore, snapshot
from server.database import Base, Profile, Source, make_engine, session_factory
from server.platform_settings import PlatformSettings


def test_backup_encryption_rejects_wrong_key_and_tampering(tmp_path):
    path, key = tmp_path / "records.enc", os.urandom(32)
    with encrypted_writer(path, key) as write: write(b"private source material")
    assert b"private source material" not in path.read_bytes()
    decrypt_to(path, tmp_path / "valid", key)
    assert (tmp_path / "valid").read_bytes() == b"private source material"
    with pytest.raises(InvalidTag): decrypt_to(path, tmp_path / "wrong", os.urandom(32))
    value = bytearray(path.read_bytes()); value[-20] ^= 1; path.write_bytes(value)
    with pytest.raises(InvalidTag): decrypt_to(path, tmp_path / "tampered", key)


def test_application_record_restore_refuses_source_or_nonempty_target(tmp_path):
    source = make_engine("sqlite+pysqlite:///" + str(tmp_path / "source.db"))
    target = make_engine("sqlite+pysqlite:///" + str(tmp_path / "target.db"))
    Base.metadata.create_all(source); Base.metadata.create_all(target)
    with session_factory(source).begin() as db:
        db.add(Profile(id="fixture-user", email="fixture@example.test", display_name="Fixture"))
    key, directory, settings = os.urandom(32), tmp_path / "backup", PlatformSettings()
    result = snapshot(source, directory, key, settings)
    assert result["records"] == 1 and not result["object_bytes_included"]
    with pytest.raises(ValueError, match="different database"): restore(source, directory, key, settings)
    restored = restore(target, directory, key, settings)
    assert restored["records"] == 1 and restored["auth_restoration_still_required"]
    with session_factory(target)() as db: assert db.scalar(select(Profile)).display_name == "Fixture"
    with pytest.raises(ValueError, match="EMPTY"): restore(target, directory, key, settings)
    source.dispose(); target.dispose()


def test_original_objects_are_encrypted_and_restored_to_empty_separate_bucket(tmp_path):
    source = make_engine("sqlite+pysqlite:///" + str(tmp_path / "source.db"))
    target = make_engine("sqlite+pysqlite:///" + str(tmp_path / "target.db"))
    Base.metadata.create_all(source); Base.metadata.create_all(target)
    with session_factory(source).begin() as db:
        db.add(Profile(id="fixture", email="fixture@example.test", display_name="Fixture")); db.flush()
        db.add(Source(owner_id="fixture", title="Private original fixture", kind="image", object_key="sources/fixture/original.png",
            metadata_json={'preview_keys': ['sources/fixture/previews/page-1.png']}))
    class Objects:
        def __init__(self): self.values = {}
        def download(self, key, path, limit): path.write_bytes(self.values[key])
        def put(self, key, path, mime): self.values[key] = path.read_bytes()
        def empty(self): return not self.values
    original, destination = Objects(), Objects()
    original.values["sources/fixture/original.png"] = b"private source bytes; not a real image"
    original.values['sources/fixture/previews/page-1.png'] = b'private preview fixture bytes'
    key, directory = os.urandom(32), tmp_path / "backup"
    source_settings, target_settings = PlatformSettings(s3_bucket="source"), PlatformSettings(s3_bucket="drill")
    snapshot(source, directory, key, source_settings, include_objects=True, objects=original)
    assert not any(b"private source bytes" in path.read_bytes() for path in (directory / "objects").iterdir())
    restored = restore(target, directory, key, target_settings, objects=destination)
    assert destination.values == original.values and restored["objects"] == 2
    source.dispose(); target.dispose()
