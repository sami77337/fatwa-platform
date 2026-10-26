"""Guarded opt-in tests through the repository's trusted synthetic test runner."""

import argparse
import json
import os

from .guard import PrerequisiteUnavailable, require_target, validate_environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgresql", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        validate_environment(os.environ)
    except PrerequisiteUnavailable as error:
        print(json.dumps({"postgresql": "NOT_RUN", "reason": str(error)}))
        return 2
    try:
        import django

        django.setup()
        require_target(test_database=False)
    except Exception:
        print(json.dumps({"postgresql": "NOT_RUN", "reason": "SYNTHETIC_PREREQUISITE_UNAVAILABLE"}))
        return 2
    try:
        from tests.wave7_foundation.runner import Wave7TestRunner

        runner = Wave7TestRunner(verbosity=2, interactive=False, keepdb=False, parallel=0)
        failures = runner.run_tests(["tests.fast9_pg_reference_consistency.postgresql"])
    except Exception:
        # No connection strings, credentials or row contents in the public report.
        print(json.dumps({"postgresql": "ERROR", "reason": "GUARDED_RUN_FAILED"}))
        return 1
    print(json.dumps({"postgresql": "FAIL" if failures else "PASS", "synthetic_only": True}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
