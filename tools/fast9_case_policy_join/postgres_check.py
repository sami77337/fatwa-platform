"""Optional non-mutation acceptance in an already authorized synthetic cluster.

No defaults, provisioning, initialization, credential discovery or migration calls.
Only the existing trusted Wave7 runner may create its disposable test database.
"""

import json
import os
import sys

BASE = "wave7_synthetic_fast9_case_policy_join"
EXPECTED = {
    "FATWA_PRODUCTION": "0",
    "FATWA_WAVE7_SYNTHETIC_WRITES": "1",
    "DJANGO_SETTINGS_MODULE": "config.settings.wave7_test",
    "PGHOST": "127.0.0.1",
    "PGPORT": "55439",
    "PGUSER": "wave7_synthetic",
    "PGDATABASE": BASE,
    "PGTESTDATABASE": "test_" + BASE,
}


def _not_run(reason):
    print(
        json.dumps(
            {
                "postgres": "NOT_RUN",
                "reason": reason,
                "allowed": False,
                "effect": "DENY",
                "owner_policy_connection": "NOT_CONNECTED",
            }
        )
    )
    return 3


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args != ["--preauthorized-disposable-only"]:
        return _not_run("EXPLICIT_OPT_IN_REQUIRED")
    if any(os.environ.get(key) != value for key, value in EXPECTED.items()):
        return _not_run("EXACT_CONFIGURATION_REQUIRED")
    if any(
        os.environ.get(key)
        for key in (
            "DATABASE_URL",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGPASSFILE",
            "PGOPTIONS",
        )
    ):
        return _not_run("UNSAFE_CONNECTION_OVERRIDE")

    import django
    from django.conf import settings

    django.setup()
    from apps.intake_workflow.guards import SyntheticWriteDenied, require_synthetic_write
    from tests.wave7_foundation.runner import Wave7TestRunner

    if settings.TEST_RUNNER != "tests.wave7_foundation.runner.Wave7TestRunner":
        return _not_run("TRUSTED_RUNNER_REQUIRED")
    try:
        # Exact runtime DB/role/version/ownership verified before any creation.
        context = require_synthetic_write(synthetic_fixtures_only=True)
        if context.database_name != BASE:
            return _not_run("ACTUAL_DATABASE_IDENTITY_MISMATCH")
    except SyntheticWriteDenied:
        return _not_run("DATABASE_UNAVAILABLE_OR_UNTRUSTED")
    failures = Wave7TestRunner(interactive=False, verbosity=2).run_tests(
        ["tests.fast9_case_policy_join.pg_acceptance"]
    )
    print(
        json.dumps(
            {
                "postgres": "FAIL" if failures else "PASS",
                "allowed": False,
                "effect": "DENY",
                "owner_policy_connection": "NOT_CONNECTED",
                "scope": "SYNTHETIC_NON_MUTATION_ONLY",
            }
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
