"""Opt-in only: the existing trusted runner owns synthetic test DB lifecycle."""

import json
import os

BASE_DATABASE = "wave7_synthetic_fast9_case_source_join"
TEST_DATABASE = "test_" + BASE_DATABASE
TRUSTED_RUNNER = "tests.wave7_foundation.runner.Wave7TestRunner"


def require_target(env):
    expected = {
        "DJANGO_SETTINGS_MODULE": "config.settings.wave7_test",
        "FATWA_PRODUCTION": "0",
        "FATWA_WAVE7_SYNTHETIC_WRITES": "1",
        "FATWA_WAVE7_SYNTHETIC_READS": "1",
        "FATWA_FAST9_CASE_SOURCE_JOIN_PG": "1",
        "PGHOST": "127.0.0.1",
        "PGDATABASE": BASE_DATABASE,
        "PGTESTDATABASE": TEST_DATABASE,
        "PGUSER": "wave7_synthetic",
    }
    if any(env.get(k) != v for k, v in expected.items()):
        raise ValueError("exact_preauthorized_synthetic_target_required")
    port = env.get("PGPORT", "")
    if (
        not port.isascii()
        or not port.isdecimal()
        or not 1 <= int(port) <= 65535
        or not env.get("PGPASSWORD")
    ):
        raise ValueError("explicit_connection_required")
    if any(
        env.get(k)
        for k in (
            "DATABASE_URL",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGPASSFILE",
            "PGOPTIONS",
        )
    ):
        raise ValueError("connection_override_rejected")


def run():
    try:
        require_target(os.environ)
    except ValueError:
        print(json.dumps({"postgresql": "NOT_RUN", "reason": "synthetic_target_not_authorized"}))
        return 2
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    from apps.intake_workflow.guards import require_synthetic_write

    if settings.TEST_RUNNER != TRUSTED_RUNNER:
        raise RuntimeError("trusted_synthetic_runner_required")
    # Read-only ownership/actual DB, role, PG major, schema checks BEFORE the
    # runner creates its test DB. Never initialize/claim an unknown base here.
    context = require_synthetic_write(synthetic_fixtures_only=True)
    if context.database_name != BASE_DATABASE:
        raise RuntimeError("synthetic_base_identity_mismatch")
    call_command(
        "test",
        "tests.fast9_case_source_join.postgresql",
        interactive=False,
        verbosity=2,
        keepdb=False,
        parallel=1,
        testrunner=TRUSTED_RUNNER,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
