"""Affected V12 P0 matrix; each recovery suite gets its own fresh owned cluster."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

LABELS = (
    "tests.casework.test_v12_administration",
    "apps.platform_recovery.v12_maintenance_tests",
    "tests.casework.test_v11_maintenance",
    "tests.v12_security_review.test_maintenance",
    "tests.v12_security_review.test_recovery",
    "tests.v12_security_review.test_rights",
    "apps.source_rights.test_strict",
    "apps.source_rights.tests",
    "apps.research_workspace.test_source_rights",
    "apps.research_workspace.tests",
    "apps.case_citations.tests",
    "apps.knowledge_links.tests",
    "apps.experimental_publication.tests",
    "apps.library_preview.tests",
    "tests.casework.test_v11_rights_boundaries",
    "tests.casework.test_v11_answer_rights",
    "apps.answer_media.tests",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--major", required=True, choices=("17", "18"))
    parser.add_argument("--functional-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.functional_worker:
        import django
        from django.core.management import call_command

        django.setup()
        call_command("check")
        call_command("makemigrations", check=True, dry_run=True, verbosity=1)
        call_command("test", *LABELS, interactive=False, verbosity=2)
        return 0
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != os.environ.get("EXPECTED_SHA", head):
        parser.error("checked-out SHA differs from EXPECTED_SHA")
    subprocess.run(["git", "diff", "--exit-code", "--quiet"], check=True)
    pg_bin = str(args.pg_bin.resolve(strict=True))
    logs = Path(f".local/qa/v12/p0-pg{args.major}")
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "tested-sha.txt").write_text(head + "\n")
    print("TESTED_SHA=" + head, flush=True)
    env = {
        **os.environ,
        "V12_PG_BIN": pg_bin,
        "FATWA_TEST_PG_BIN": pg_bin,
        "FATWA_RECOVERY_PG_BIN": pg_bin,
    }
    ordinary = "config.settings.campaign_review"
    stages = (
        ("functional-security", ordinary,
         ["-m", "infra.dev.v12_verify", "--pg-bin", pg_bin, "--major", args.major,
          "--functional-worker"]),
        ("strict-recovery", ordinary,
         ["-m", "apps.platform_recovery.v12_recovery_tests", "--pg-bin", pg_bin]),
        ("encrypted-v11-regression", ordinary,
         ["-m", "apps.platform_recovery.tests_v11", "--pg-bin", pg_bin]),
        ("isolated-v10-compatibility", "apps.platform_recovery.v12_recovery_v10_test_settings",
         ["-m", "apps.platform_recovery.tests", "--pg-bin", pg_bin]),
    )
    for name, profile, command in stages:
        full = [sys.executable, "infra/dev/with_casework_postgres.py", "--pg-bin", pg_bin,
                "--major", args.major, "--settings", profile, "--", sys.executable, *command]
        with (logs / (name + ".log")).open("w") as output:
            result = subprocess.run(full, env=env, stdout=output, stderr=subprocess.STDOUT)
        print(name.upper() + " EXIT=" + str(result.returncode), flush=True)
        print((logs / (name + ".log")).read_text(), flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
