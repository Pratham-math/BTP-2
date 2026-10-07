"""Bounded, cancellable child processes; never terminate an unrelated runtime."""

import os
import signal
import subprocess
import tempfile
import time
from contextvars import ContextVar
from pathlib import Path
from threading import Event, Lock, Thread

from server.providers.base import GenerationError
from server.owned_process import close_owned_job, spawn_owned


CURRENT_CONTROL = ContextVar("generation_control", default=None)


class JobControl:
    def __init__(self, folder: Path, timeout: float | None = None):
        self.cancel_requested = Event()
        self.state_lock = Lock()
        self.folder = folder
        self.deadline = time.monotonic() + (timeout or float(os.getenv("JOB_TIMEOUT_SECONDS", "3600")))
        self._last_disk_check = 0.0

    def check(self):
        if self.cancel_requested.is_set():
            raise GenerationError("CANCELLED", "Generation was cancelled. Completed artifacts are saved.")
        if time.monotonic() > self.deadline:
            raise GenerationError("JOB_TIMEOUT", "This job exceeded its time limit. Completed work is saved.",
                                  "Retry or choose a smaller local model / preview quality.")
        if time.monotonic() - self._last_disk_check > 5:
            import shutil
            self._last_disk_check = time.monotonic()
            free = shutil.disk_usage(self.folder).free
            minimum = int(os.getenv("MIN_FREE_DISK_MB", "512")) * 1024 * 1024
            used = 0
            for path in self.folder.rglob("*"):
                try:
                    if path.is_file():
                        used += path.stat().st_size
                except FileNotFoundError:
                    continue  # Manim may remove its own temporary files between polls.
            limit = int(os.getenv("MAX_JOB_DISK_MB", "2048")) * 1024 * 1024
            if free < minimum or used > limit:
                raise GenerationError("DISK_FULL", "Storage space is below the job's safety limit.",
                                      "Free disk space before resuming this job.")


def checkpoint():
    control = CURRENT_CONTROL.get()
    if control:
        control.check()


class JobHeartbeat:
    def __init__(self, storage, job_id):
        self.stop_requested = Event()
        def pulse():
            from server.storage import now_iso
            while not self.stop_requested.wait(5):
                try:
                    storage.update_status(job_id, heartbeat_at=now_iso())
                except (OSError, ValueError):
                    return
        self.thread = Thread(target=pulse, name="video-heartbeat", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_requested.set()
        self.thread.join(timeout=2)


def stop_process(process: subprocess.Popen):
    if close_owned_job(process):
        process.wait(timeout=15)
        return
    if process.poll() is not None:
        return
    if os.name == "nt":
        # /T includes descendants spawned by this owned Manim/Piper process.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=15)


def run_command(command: list[str], cwd: Path | None = None, timeout: float = 60,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    checkpoint()
    child_environment = {key: value for key, value in (os.environ if env is None else env).items()
                         if key.upper() not in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}}
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        try:
            process = spawn_owned(command, cwd=cwd, env=child_environment, shell=False,
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **options)
        except FileNotFoundError as error:
            raise GenerationError("DEPENDENCY_MISSING", f"Required executable is missing: {Path(command[0]).name}") from error
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                checkpoint()
                if time.monotonic() > deadline:
                    raise GenerationError("STAGE_TIMEOUT", f"{Path(command[0]).name} exceeded its time limit.")
                time.sleep(.1)
            checkpoint()
        except BaseException:
            stop_process(process)
            raise
        finally:
            close_owned_job(process)
        stdout.seek(0)
        stderr.seek(0)
        out = stdout.read(1_048_577).decode("utf-8", errors="replace")
        err = stderr.read(1_048_577).decode("utf-8", errors="replace")
        if process.returncode:
            # Child diagnostics can contain private source text. Do not echo them.
            raise GenerationError("PROCESS_FAILED", f"{Path(command[0]).name} failed (exit {process.returncode}).")
        if len(out) > 1_048_576:
            raise GenerationError("OUTPUT_LIMIT", "A child process exceeded its output limit.")
        return subprocess.CompletedProcess(command, process.returncode, out, err)


class RuntimeLease:
    """One coordinator process per data directory, including on Windows."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / ".runtime.lock"
        self.file = None

    def acquire(self):
        self.file = self.path.open("a+b")
        self.file.seek(0)
        if self.path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            self.file = None
            raise RuntimeError("Another backend owns this data directory. Use one Uvicorn worker.") from error

    def release(self):
        if self.file:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None
