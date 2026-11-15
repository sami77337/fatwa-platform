"""Strict exact-SHA browser acceptance on owned synthetic PostgreSQL."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import django
    django.setup()
    from django.db import connection
    from tests.wave7_foundation.runner import Wave7TestRunner

    result = None
    output = ROOT / ".local/qa/requester-tracking/browser-result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status":"ERROR","deployment":"NOT_DEPLOYED","tests_run":0}
    class Runner(Wave7TestRunner):
        def run_suite(self, suite, **kwargs):
            nonlocal result
            result = super().run_suite(suite, **kwargs)
            return result
    try:
        report["tested_sha"] = subprocess.check_output(
            ["git","rev-parse","HEAD"], cwd=ROOT, text=True,
        ).strip()
        if report["tested_sha"] != os.environ["EXPECTED_SHA"]:
            raise RuntimeError("unexpected_tested_revision")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')::int / 10000")
            major = cursor.fetchone()[0]
        report["postgresql_major"] = major
        if str(major) != os.environ["PG_EXPECTED_MAJOR"]:
            raise RuntimeError("unexpected_postgres_major")
        failure = Runner(verbosity=2,interactive=False).run_tests([
            "tests.delivery_queue.test_requester_tracking_browser",
        ])
        report.update(
            tests_run=result.testsRun, failures=len(result.failures),
            errors=len(result.errors), skipped=len(result.skipped),
        )
        report["status"] = (
            "PASS" if not failure and result.wasSuccessful()
            and result.testsRun == 1 and not result.skipped
            else "FAIL"
        )
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("REQUESTER_BROWSER_RESULT="+json.dumps(report,sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
