"""Contain one acceptance browser tree for the lifetime of the Node stdin pipe.

Node starts this helper in a new session on POSIX. Windows containment is a job
assigned before Chrome can spawn descendants; no browser security flags change.
Only protocol events go to stdout. Browser diagnostics inherit stderr.
"""

import ctypes
import errno
import json
import os
import signal
import subprocess
import sys
import threading


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


def windows_job():
    """Own a non-inheritable job handle; descendants inherit membership only."""
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IOCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IOCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)
        raise error
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)
        raise error

    def terminate():
        # Includes this supervisor. The handle also closes if Node kills us.
        if not kernel.TerminateJobObject(job, 0):
            os._exit(1)  # KILL_ON_JOB_CLOSE remains the fallback.

    return terminate


def containment():
    if os.name == "nt":
        return windows_job()
    if os.getpgrp() != os.getpid():
        raise RuntimeError("supervisor requires an isolated process group")
    return lambda: os.killpg(os.getpgrp(), signal.SIGKILL)


def main():
    try:
        terminate = containment()
    except (OSError, RuntimeError):
        emit("error", code="CONTAINMENT_SETUP_FAILED")
        return 1
    try:
        try:
            browser = subprocess.Popen(
                sys.argv[1:],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
                close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, ValueError) as error:
            emit("error", code=errno.errorcode.get(getattr(error, "errno", None), "SPAWN_FAILED"))
        else:
            emit("spawned", pid=browser.pid)

            def monitor():
                emit("exit", code=browser.wait())

            threading.Thread(target=monitor, daemon=True).start()
        # Keep containment alive after an early browser exit. A broken/closed
        # Node control pipe triggers the same cleanup as a normal completion.
        while sys.stdin.buffer.read(1):
            pass
    finally:
        terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
