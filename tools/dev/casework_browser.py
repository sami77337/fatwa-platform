"""Strict exact-SHA, actual-Chrome acceptance against owned synthetic PostgreSQL."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    report = {
        "status": "ERROR",
        "deployment": "NOT_DEPLOYED",
        "acceptance": "ACCEPTANCE_HOLD",
        "tests_run": 0,
    }
    output = ROOT / ".local/qa/v6-casework/browser-result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = None
    try:
        import django

        django.setup()
        from django.db import connection

        from tests.wave7_foundation.runner import Wave7TestRunner

        class Runner(Wave7TestRunner):
            def run_suite(self, suite, **kwargs):
                nonlocal result
                result = super().run_suite(suite, **kwargs)
                return result

        report["tested_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
        if report["tested_sha"] != os.environ["EXPECTED_SHA"]:
            raise RuntimeError("unexpected_tested_revision")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')::int / 10000")
            major = cursor.fetchone()[0]
        report["postgresql_major"] = major
        if str(major) != os.environ["PG_EXPECTED_MAJOR"]:
            raise RuntimeError("unexpected_postgresql_major")
        failed = Runner(verbosity=2, interactive=False).run_tests(["tests.casework.test_browser"])
        if result is not None:
            report.update(
                tests_run=result.testsRun,
                failures=len(result.failures),
                errors=len(result.errors),
                skipped=len(result.skipped),
            )
        report["status"] = (
            "PASS"
            if (
                not failed
                and result is not None
                and result.wasSuccessful()
                and result.testsRun == 1
                and not result.skipped
            )
            else "FAIL"
        )
    except Exception as exc:
        # Do not serialize connection details, credentials or private response bodies.
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("CASEWORK_BROWSER_RESULT=" + json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
