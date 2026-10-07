"""Cancellation really stops an owned process and its child."""

import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from server.providers.base import GenerationError
from server.runtime import CURRENT_CONTROL, JobControl, run_command
from server.owned_process import python_image


def alive(pid):
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            status = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(status)) and status.value == 259)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_media_commands_do_not_inherit_cloud_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-fixture-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "private-google-fixture-key")
    result = run_command([sys.executable, "-c", "import os,sys; print('GEMINI_API_KEY' in os.environ, 'GOOGLE_API_KEY' in os.environ); print(sys.prefix)"], timeout=10)
    assert result.stdout.splitlines() == ["False False", sys.prefix]


def test_cancellation_stops_owned_process_tree(tmp_path):
    pid_file = tmp_path / "owned-processes.txt"
    script = ("import os,subprocess,sys,time; from pathlib import Path; "
              "child=subprocess.Popen([sys.argv[2],'-c','import time; time.sleep(30)']); "
              "Path(sys.argv[1]).write_text(str(os.getpid())+' '+str(child.pid)); time.sleep(30)")
    control, errors = JobControl(tmp_path, timeout=10), []
    def execute():
        token = CURRENT_CONTROL.set(control)
        try:
            run_command([sys.executable, "-c", script, str(pid_file), python_image()], timeout=10)
        except GenerationError as error:
            errors.append(error)
        finally:
            CURRENT_CONTROL.reset(token)
    worker = threading.Thread(target=execute)
    worker.start()
    deadline = time.monotonic() + 5
    try:
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert pid_file.exists(), "Owned process did not start"
        parent, child = map(int, pid_file.read_text().split())
        assert alive(parent) and alive(child)
    finally:
        control.cancel_requested.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors and errors[0].code == "CANCELLED"
    assert not alive(parent) and not alive(child)


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel owns this lifetime guarantee")
def test_backend_exit_stops_owned_process_tree(tmp_path):
    pid_file = tmp_path / "crash-processes.txt"
    child_code = ("import os,subprocess,sys,time; from pathlib import Path; "
                  "child=subprocess.Popen([sys.argv[2],'-c','import time; time.sleep(30)']); "
                  "Path(sys.argv[1]).write_text(str(os.getpid())+' '+str(child.pid)); time.sleep(30)")
    coordinator_code = ("import os,sys; from pathlib import Path; from server.runtime import run_command; "
                        "Path(sys.argv[1]+'.owner').write_text(str(os.getpid())); "
                        "run_command([sys.executable,'-c',sys.argv[2],sys.argv[1],sys.argv[3]],timeout=30)")
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}}
    environment["__PYVENV_LAUNCHER__"] = sys.executable
    coordinator = subprocess.Popen([python_image(), "-c", coordinator_code, str(pid_file), child_code, python_image()],
                                   env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    parent = child = None
    try:
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert pid_file.exists(), "Owned render did not start"
        parent, child = map(int, pid_file.read_text().split())
        owner = int(pid_file.with_suffix(".txt.owner").read_text())
        assert alive(owner) and alive(parent) and alive(child)
        # Kill only the backend, with no taskkill /T assistance.
        os.kill(owner, signal.SIGTERM)
        coordinator.wait(timeout=5)
        deadline = time.monotonic() + 5
        while (alive(parent) or alive(child)) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not alive(parent) and not alive(child)
    finally:
        if coordinator.poll() is None:
            coordinator.kill()
            coordinator.wait(timeout=5)
        for pid in (parent, child):
            if pid and alive(pid):
                os.kill(pid, signal.SIGTERM)
