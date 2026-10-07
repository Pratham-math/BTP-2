"""Windows child lifetime: backend exit closes the job and kills its tree.

The child starts suspended so its descendants inherit ownership before any
application code runs. This never attaches an existing Ollama service.
Windows API contract: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
"""

import os
import subprocess
import sys
import time


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                    ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", _BasicLimits), ("io", _IoCounters),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    class _ThreadEntry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("thread_id", wintypes.DWORD), ("process_id", wintypes.DWORD),
                    ("priority", wintypes.LONG), ("delta_priority", wintypes.LONG), ("flags", wintypes.DWORD)]

    class _Accounting(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in
                    ("user_time", "kernel_time", "period_user_time", "period_kernel_time")]
        _fields_ += [(name, wintypes.DWORD) for name in
                     ("page_faults", "total_processes", "active_processes", "terminated_processes")]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, result_type, argument_types in (
        ("CreateJobObjectW", wintypes.HANDLE, [ctypes.c_void_p, wintypes.LPCWSTR]),
        ("SetInformationJobObject", wintypes.BOOL, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]),
        ("AssignProcessToJobObject", wintypes.BOOL, [wintypes.HANDLE, wintypes.HANDLE]),
        ("QueryInformationJobObject", wintypes.BOOL, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                     wintypes.DWORD, ctypes.c_void_p]),
        ("TerminateJobObject", wintypes.BOOL, [wintypes.HANDLE, wintypes.UINT]),
        ("CreateToolhelp32Snapshot", wintypes.HANDLE, [wintypes.DWORD, wintypes.DWORD]),
        ("Thread32First", wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]),
        ("Thread32Next", wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]),
        ("OpenThread", wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
        ("ResumeThread", wintypes.DWORD, [wintypes.HANDLE]),
        ("CloseHandle", wintypes.BOOL, [wintypes.HANDLE]),
        ("GetModuleFileNameW", wintypes.DWORD, [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD]),
    ):
        function = getattr(_kernel, name)
        function.restype, function.argtypes = result_type, argument_types

    class _WindowsJob:
        def __init__(self):
            # NULL security attributes keep the sole handle non-inheritable.
            self.handle = _kernel.CreateJobObjectW(None, None)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                error = ctypes.WinError(ctypes.get_last_error())
                self.close()
                raise error

        def assign(self, process):
            if not _kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())

        def close(self):
            if not self.handle:
                return
            try:
                # Closing a job kills asynchronously. Wait for the whole tree
                # before allowing another render to reuse the same artifacts.
                if not _kernel.TerminateJobObject(self.handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
                deadline = time.monotonic() + 15
                while True:
                    accounting = _Accounting()
                    if not _kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting),
                                                             ctypes.sizeof(accounting), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not accounting.active_processes:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Owned child processes did not exit within 15 seconds")
                    time.sleep(.01)
            finally:
                _kernel.CloseHandle(self.handle)
                self.handle = None

    def _resume_new_process(process):
        # CREATE_SUSPENDED leaves exactly the initial thread to resume.
        snapshot = _kernel.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            available = _kernel.Thread32First(snapshot, ctypes.byref(entry))
            while available:
                if entry.process_id == process.pid:
                    thread = _kernel.OpenThread(0x2, False, entry.thread_id)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if _kernel.ResumeThread(thread) != 1:
                            raise OSError("The owned process did not have one suspended initial thread")
                    finally:
                        _kernel.CloseHandle(thread)
                    return
                entry.size = ctypes.sizeof(entry)
                available = _kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("The owned process's initial thread was not found")
        finally:
            _kernel.CloseHandle(snapshot)


def python_image() -> str:
    """The running interpreter image, avoiding Windows Store execution aliases."""
    if os.name != "nt":
        return sys.executable
    buffer = ctypes.create_unicode_buffer(32768)
    length = _kernel.GetModuleFileNameW(None, buffer, len(buffer))
    if not length or length >= len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def spawn_owned(command, **options) -> subprocess.Popen:
    """Start only a new child; caller closes its ownership after completion."""
    if os.name != "nt":
        return subprocess.Popen(command, **options)
    if os.path.normcase(os.path.abspath(command[0])) == os.path.normcase(os.path.abspath(sys.executable)):
        # Store aliases can use a broker outside the process tree. Launch the
        # current native image directly while retaining this virtual environment.
        command = [python_image(), *command[1:]]
        options["env"] = dict(options.get("env") or os.environ)
        options["env"]["__PYVENV_LAUNCHER__"] = sys.executable
    job = _WindowsJob()
    process = None
    try:
        options["creationflags"] = options.get("creationflags", 0) | 0x4  # CREATE_SUSPENDED
        process = subprocess.Popen(command, **options)
        job.assign(process)
        _resume_new_process(process)
        process._owned_job = job
        return process
    except BaseException:
        try:
            job.close()
        finally:
            if process:
                process.kill()
                process.wait(timeout=15)
        raise


def close_owned_job(process) -> bool:
    job = getattr(process, "_owned_job", None)
    if job:
        process._owned_job = None
        job.close()
        return True
    return False
