"""Run only this lane's synthetic regression suite and print truthful JSON evidence."""

import hashlib
import json
import os
import platform
import subprocess
import sys
import unittest
from pathlib import Path

from .fixtures import fixture_inventory

ROOT = Path(__file__).resolve().parents[2]
OWNED = ("tests/fast8_ingest_adversarial", "tools/fast8_ingest_adversarial")


def git(*arguments):
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, timeout=10, check=False
    )
    return (
        result.stdout.decode("utf-8", errors="strict").strip() if result.returncode == 0 else None
    )


def main():
    # Also inherited by CLI children. No source archives or database are read.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    suite = unittest.defaultTestLoader.discover(str(ROOT / OWNED[0]), pattern="test_*.py")
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    files = {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for directory in OWNED
        for path in sorted((ROOT / directory).rglob("*.py"))
    }
    report = {
        "schema": "fatwa.fast8-ingest-adversarial.qa.v1",
        "status": "PASS" if result.wasSuccessful() and result.testsRun else "FAIL",
        "python": platform.python_version(),
        "head_sha": git("rev-parse", "HEAD"),
        "owned_status_porcelain": git("status", "--porcelain", "--", *OWNED),
        "test_methods_run": result.testsRun,
        "failure_events": len(result.failures),
        "error_events": len(result.errors),
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "failing_ids": [test.id() for test, _ in result.failures + result.errors],
        "fixture_seeds": fixture_inventory(),
        "owned_python_sha256": files,
        "owner_archives": "NOT_SUPPLIED / NOT_ACCESSED",
        "postgresql": "NOT_RUN",
        "browser": "NOT_RUN (pure ingestion boundary scope)",
        "gates": "B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING",
    }
    sys.stdout.buffer.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
