"""Focused V10 checks inside the existing owned PostgreSQL helper; no external services."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

LABELS = (
    "apps.mufti_workspace.tests",
    "apps.requester_portal.tests",
    "apps.library_preview.tests",
    "apps.source_case_intake.http_tests",
    "apps.composite_delivery.test_desk",
    "tests.casework.test_v10_integration",
    "tests.casework.test_v9_integration.OriginStorageDeliveryTests."
    "test_staff_handoff_requires_current_signed_plan_and_never_sends",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    logs = Path(".local/qa/v10")
    logs.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if os.environ.get("EXPECTED_SHA", head) != head:
        parser.error("checked-out head does not match EXPECTED_SHA")
    (logs / "tested-sha.txt").write_text(head + "\n")
    print("TESTED_SHA=" + head, flush=True)
    env = {**os.environ, "FATWA_RECOVERY_PG_BIN": str(args.pg_bin.resolve(strict=True))}
    commands = [
        ("system", ["manage.py", "check"]),
        ("drift", ["manage.py", "makemigrations", "--check", "--dry-run"]),
        ("tests", ["manage.py", "test", *LABELS, "--noinput", "--verbosity", "2"]),
        (
            "recovery",
            ["-m", "apps.platform_recovery.tests", "--pg-bin", env["FATWA_RECOVERY_PG_BIN"]],
        ),
    ]
    if args.browser:
        commands.append(
            (
                "browser",
                [
                    "manage.py",
                    "test",
                    "tests.casework.test_v10_browser",
                    "--noinput",
                    "--verbosity",
                    "2",
                ],
            )
        )
    for name, command in commands:
        with (logs / (name + ".log")).open("w", encoding="utf-8") as output:
            result = subprocess.run(
                [sys.executable, *command], env=env, stdout=output, stderr=subprocess.STDOUT
            )
        print(name.upper() + " EXIT=" + str(result.returncode), flush=True)
        print((logs / (name + ".log")).read_text(), flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
