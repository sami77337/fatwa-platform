"""Real synthetic process trees exercise browser containment, without Chrome."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SUPERVISOR = Path(__file__).with_name("browser_supervisor.py")


def running(pid):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        # An orphan awaiting init's reap is no longer an executing child.
        stat = Path(f"/proc/{pid}/stat")
        return not stat.exists() or stat.read_text().split(") ", 1)[1][0] != "Z"
    except (ProcessLookupError, FileNotFoundError):
        # The child can be reaped after exists() but before reading /proc/stat.
        return False


class BrowserSupervisorTests(unittest.TestCase):
    def launch(self, command):
        process = subprocess.Popen(
            [sys.executable, "-u", str(SUPERVISOR), *command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.addCleanup(self.stop, process)
        return process

    @staticmethod
    def stop(process):
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()

    def event(self, process):
        # Poll a reader thread so a broken protocol cannot hang the test suite.
        import queue
        import threading

        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        line = lines.get(timeout=5)
        self.assertTrue(line, "supervisor closed without a protocol event")
        return json.loads(line)

    def assert_stopped(self, pid):
        deadline = time.monotonic() + 5
        while running(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(running(pid), f"synthetic child {pid} survived cleanup")

    def tree(self, early_exit):
        directory = tempfile.TemporaryDirectory(prefix="fatwa-supervisor-test-")
        self.addCleanup(directory.cleanup)
        marker = Path(directory.name, "grandchild.pid")
        child_code = (
            "import subprocess,sys,time; from pathlib import Path; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            f"Path({str(marker)!r}).write_text(str(child.pid)); "
            + ("sys.exit(7)" if early_exit else "time.sleep(60)")
        )
        process = self.launch([sys.executable, "-c", child_code])
        event = self.event(process)
        self.assertEqual(event["event"], "spawned")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if marker.exists() and marker.read_text().strip():
                break
            time.sleep(0.02)
        grandchild = int(marker.read_text())
        return process, event["pid"], grandchild

    def test_stdin_eof_kills_live_browser_and_grandchild(self):
        process, browser, grandchild = self.tree(early_exit=False)
        self.assertTrue(running(browser))
        self.assertTrue(running(grandchild))
        process.stdin.close()
        process.wait(timeout=5)
        self.assert_stopped(browser)
        self.assert_stopped(grandchild)

    def test_early_browser_exit_keeps_grandchild_contained_until_cleanup(self):
        process, browser, grandchild = self.tree(early_exit=True)
        self.assertEqual(self.event(process), {"event": "exit", "code": 7})
        self.assertIsNone(process.poll())
        self.assertTrue(running(grandchild))
        process.stdin.close()
        process.wait(timeout=5)
        self.assert_stopped(browser)
        self.assert_stopped(grandchild)

    def test_missing_executable_reports_spawn_failure(self):
        with tempfile.TemporaryDirectory(prefix="fatwa-supervisor-missing-") as directory:
            process = self.launch([str(Path(directory, "does-not-exist"))])
            self.assertEqual(self.event(process), {"event": "error", "code": "ENOENT"})
            process.stdin.close()
            process.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt", "Windows job handle lifetime")
    def test_killed_supervisor_closes_job_and_kills_descendants(self):
        process, browser, grandchild = self.tree(early_exit=False)
        process.kill()
        process.wait(timeout=5)
        self.assert_stopped(browser)
        self.assert_stopped(grandchild)

    @unittest.skipIf(os.name == "nt", "POSIX process group ownership")
    def test_unisolated_supervisor_refuses_to_launch(self):
        result = subprocess.run(
            [sys.executable, str(SUPERVISOR), sys.executable, "-c", "print('unsafe')"],
            input="",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout),
            {"event": "error", "code": "CONTAINMENT_SETUP_FAILED"},
        )


if __name__ == "__main__":
    unittest.main()
