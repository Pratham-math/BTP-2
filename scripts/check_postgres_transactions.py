"""Verify real PostgreSQL locking/fencing using disposable, explicitly owned rows."""
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import delete, select
from server.database import Job, Profile, StageResult, make_engine, session_factory
from server.platform_settings import PlatformSettings
from server.providers.base import GenerationError
from server.worker.queue import JobContext, claim


def main():
    settings = PlatformSettings.from_env()
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    owner = str(uuid4())
    job_ids = [str(uuid4()), str(uuid4())]
    checks = {}
    try:
        with factory.begin() as db:
            db.add(Profile(id=owner, email="disposable-fixture@example.invalid", display_name="Disposable verification fixture"))
            db.flush()
            for identifier in job_ids:
                db.add(Job(id=identifier, owner_id=owner, dedup_key=uuid4().hex * 2,
                           kind="verification_fixture", priority=0, payload={"disposable": True}))
        # Lock one row in a separate transaction; SKIP LOCKED must immediately
        # claim the other instead of waiting behind it.
        with factory.begin() as locked:
            locked.scalar(select(Job).where(Job.id == job_ids[0]).with_for_update())
            selected = claim(factory, owner_id=owner)
            if not selected or selected["id"] != job_ids[1]:
                raise AssertionError("SKIP LOCKED did not select the other disposable job")
            checks["skip_locked"] = True
            locked.get(Job, job_ids[0]).state = "completed"
        old = JobContext(factory, selected)
        old.save("fixture", {"version": 1}, {"accepted": True})
        with factory.begin() as db:
            db.get(Job, selected["id"]).lease_until = time.time() - 1
        recovered = claim(factory, owner_id=owner)
        if recovered["id"] != selected["id"] or recovered["fence"] != selected["fence"] + 1:
            raise AssertionError("Expired lease was not fenced and recovered")
        try:
            old.finish({"stale": True})
            raise AssertionError("Stale worker was permitted to publish")
        except GenerationError:
            checks["stale_publication_rejected"] = True
        latest = JobContext(factory, recovered)
        assert latest.saved("fixture", {"version": 1}) == {"accepted": True}
        latest.finish({"accepted": True})
        checks["persisted_stage_recovered"] = True
        destination = Path(__file__).resolve().parents[1] / ".run" / "postgres-verification.json"
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print(json.dumps(checks, indent=2))
    finally:
        # Only these freshly generated fixture IDs are ever removed.
        with factory.begin() as db:
            db.execute(delete(StageResult).where(StageResult.job_id.in_(job_ids)))
            db.execute(delete(Job).where(Job.id.in_(job_ids), Job.owner_id == owner))
            db.execute(delete(Profile).where(Profile.id == owner))
        engine.dispose()


if __name__ == "__main__":
    main()
