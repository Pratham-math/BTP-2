"""Run with python -m server.worker; one heavy job per worker process."""
import argparse
import logging
import signal
import time
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import select
from server.assessment.runner import configured_runner
from server.config import PROJECT_DIR
from server.database import Attempt, Job, LearningSession, make_engine, session_factory
from server.object_store import ObjectStore
from server.platform_settings import PlatformSettings
from server.providers.base import GenerationError
from server.runtime import CURRENT_CONTROL, JobControl, RuntimeLease
from server.logging_safety import configure_safe_logs
from server.worker.queue import JobContext, claim
from server.worker.tasks import HANDLERS


log = logging.getLogger("btp2.worker")


def execute(factory, settings, data, *, objects=None, runner=None):
    context = JobContext(factory, data)
    folder = PROJECT_DIR / ".run" / "platform-worker" / data["id"]
    folder.mkdir(parents=True, exist_ok=True)
    control, stop = JobControl(folder), Event()
    token = CURRENT_CONTROL.set(control)
    if settings.local:
        from server.local_services import LocalObjectStore
        objects = objects or LocalObjectStore()
    runner = runner or configured_runner(settings)
    objects = objects or ObjectStore(settings)

    def pulse():
        while not stop.wait(15):
            try:
                context.heartbeat()
            except Exception:
                control.cancel_requested.set()
                return
    thread = Thread(target=pulse, daemon=True)
    thread.start()
    try:
        handler = HANDLERS.get(data["kind"])
        if not handler:
            raise GenerationError("UNKNOWN_JOB", "This job type is not supported by the installed worker.")
        result = handler(context, settings, objects, runner, data["payload"], folder)
        context.finish(result)
        log.info("job=%s kind=%s state=completed", data["id"], data["kind"])
    except Exception as error:
        # Do not log exception text: SDK/parser failures can include source/code/keys.
        code = error.code if isinstance(error, GenerationError) else "SERVICE_FAILED"
        state = "waiting_for_review" if code in {"CONTENT_NEEDS_REVIEW", "ASSESSMENT_NEEDS_REVIEW", "TRACE_NEEDS_REVIEW"} else "waiting_for_input" if code in {
            "ERASURE_WORKERS_NOT_STOPPED", "ERASURE_BATCH_REQUIRED", "AUTH_ERASURE_NOT_CONFIGURED", "KEY_MISSING", "MODEL_NOT_CONFIGURED", "STORAGE_NOT_CONFIGURED", "VISION_NOT_CONFIGURED", "RUNNER_NOT_VERIFIED", "PARSER_NOT_VERIFIED", "SOURCE_NEEDS_CORRECTION", "SOURCES_REQUIRED", "CONVERSION_NOT_CONFIGURED", "SOURCE_BATCH_REQUIRED", "GENERATION_BATCH_REQUIRED"} else "failed"
        try:
            if data["kind"] == "grade":
                with context.transaction() as (db, _):
                    attempt = db.get(Attempt, data["payload"]["attempt_id"])
                    if attempt and attempt.state != "graded":
                        attempt.state, attempt.result = "service_failed", {"feedback": "The grading service failed. Your code and prior result are saved; retry grading.", "error_code": code}
                        session = db.get(LearningSession, attempt.session_id)
                        if session.route_revision == attempt.route_revision:
                            session.state = "checkpoint"
            context.finish({"message": str(error) if isinstance(error, GenerationError) else "A preparation service failed. Completed stages are saved; check service configuration and retry."}, state, code)
        except GenerationError:
            pass  # Cancellation or a recovered lease owns the final state.
        # The class name is safe to log (no message text) and makes SERVICE_FAILED diagnosable.
        log.warning("job=%s kind=%s code=%s error=%s", data["id"], data["kind"], code, type(error).__name__)
    finally:
        stop.set()
        thread.join(timeout=2)
        control.cancel_requested.set()
        CURRENT_CONTROL.reset(token)
        runner.close()
        try:
            with factory.begin() as db:
                previous = db.scalar(select(Job).where(Job.id == data['id'], Job.state == 'cancelled',
                    Job.fence == data['fence'] + 1).with_for_update(nowait=True))
                if previous:
                    previous.result = {**previous.result, 'worker_stopped': True}
        except Exception:
            log.warning('job=%s code=WORKER_STOP_ACK_FAILED', data['id'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--queue", choices=["generation", "grading", "maintenance", "all"], default="generation")
    # Jobs are claimed with SKIP LOCKED and fences, so several slots can share one queue safely.
    parser.add_argument("--slot", type=int, default=1)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    configure_safe_logs()
    settings = PlatformSettings.from_env()
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL and apply platform migrations before starting the worker.")
    if not settings.database_url.startswith("postgresql"):
        raise SystemExit("The durable worker requires PostgreSQL. SQLite is only a test fixture.")
    engine = make_engine(settings.database_url)
    factory, stopped, consecutive = session_factory(engine), Event(), 0
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    lease_dir = PROJECT_DIR / ".run" / "platform-worker" / (args.queue if args.slot == 1 else f"{args.queue}-{args.slot}")
    lease_dir.mkdir(parents=True, exist_ok=True)
    lease = RuntimeLease(lease_dir)
    lease.acquire()
    try:
        while not stopped.is_set():
            data = claim(factory, prefer_oldest=consecutive >= 5, queue=args.queue)
            if data:
                execute(factory, settings, data)
                consecutive = (consecutive + 1) % 6
            elif args.once:
                break
            else:
                stopped.wait(2)
            if args.once:
                break
    finally:
        lease.release()
        engine.dispose()


if __name__ == "__main__":
    main()
