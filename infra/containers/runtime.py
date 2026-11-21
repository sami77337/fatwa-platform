"""Run the real owned PostgreSQL and native service checks in a development image."""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LABELS = (
    "apps.staff_sessions.test_campaign.CampaignSessionTests",
    "tests.casework.test_campaign.CampaignProfileTests",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside-owned-cluster", action="store_true")
    args = parser.parse_args()
    source = os.environ.get("FATWA_CONTAINER_SOURCE", "")
    major = os.environ.get("FATWA_CONTAINER_POSTGRES_MAJOR", "")
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or os.getuid() != 10001
        or sys.version_info[:2] != (3, 13)
        or major not in {"17", "18"}
        or not re.fullmatch(r"[0-9a-f]{40}", source)
    ):
        raise SystemExit("Explicit isolated development container configuration required")
    binary = f"/usr/lib/postgresql/{major}/bin"
    if not args.inside_owned_cluster:
        # The common runner creates, owns, migrates and tears down its own cluster.
        # No inherited DATABASE_URL or host service becomes a target.
        return subprocess.run(
            [
                sys.executable,
                "infra/dev/with_casework_postgres.py",
                "--pg-bin",
                binary,
                "--major",
                major,
                "--settings",
                "config.settings.campaign_review",
                "--",
                sys.executable,
                __file__,
                "--inside-owned-cluster",
            ],
            check=False,
        ).returncode

    # Direct script execution starts sys.path in infra/containers; load the
    # committed application root, just as manage.py does for native commands.
    source_root = Path(__file__).resolve().parents[2]
    if source_root != Path.cwd():
        raise SystemExit("Run from the committed application root")
    sys.path.insert(0, str(source_root))
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection
    from django.test.utils import get_runner

    from apps.intake_workflow.guards import require_owned_database

    require_owned_database(synthetic_fixtures_only=True)
    call_command("check")
    call_command("makemigrations", check=True, dry_run=True, verbosity=1)
    try:
        Path("/app/runtime-readonly-probe").write_text("must not succeed")
    except OSError as exc:
        if exc.errno != errno.EROFS:
            raise AssertionError("The source mount must actually be read-only") from exc
    else:
        raise AssertionError("Container source filesystem accepted a write")

    # The configured runner creates the ownership witness in its test database.
    # A bare DiscoverRunner creates an unowned test database and is correctly
    # rejected by the unchanged migration admission boundary.
    runner = get_runner(settings)(verbosity=2, interactive=False)
    count = runner.build_suite(LABELS).countTestCases()
    if count != 4 or runner.run_tests(LABELS):
        raise SystemExit("Container native workspace checks did not pass")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, version()")
        database, user, postgres = cursor.fetchone()
    result = {
        "schema": "fatwa.development-container-runtime.v1",
        "status": "PASS",
        "source_sha": source,
        "python": sys.version,
        "postgres_major": int(major),
        "postgres": postgres,
        "database": database,
        "database_user": user,
        "uid": os.getuid(),
        "source_write_rejected": True,
        "native_tests": count,
        "test_labels": LABELS,
        "production": False,
        "deployment": "NOT_DEPLOYED",
    }
    print("FATWA_CONTAINER_RESULT=" + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
