"""Affected P1 checks and one connected UI/encrypted-restore journey on an owned DB."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

LABELS = (
    "apps.mufti_workspace.journey_tests",
    "apps.source_rights.v12_tests",
    "tests.casework.test_v12_library_navigation",
    # Publication collection changed: retain independently motivated P0 regressions.
    "tests.casework.test_v12_catalog_expiry",
    "tests.casework.test_v11_publication_frame",
    "apps.experimental_publication.tests_ui",
    "apps.knowledge_links.tests",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != os.environ.get("EXPECTED_SHA", head):
        parser.error("checked-out SHA differs from EXPECTED_SHA")
    subprocess.run(["git", "diff", "--exit-code", "--quiet"], check=True)
    pg_bin = str(args.pg_bin.resolve(strict=True))
    logs = Path(".local/qa/v12/p1")
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "tested-sha.txt").write_text(head + "\n")
    print("TESTED_SHA=" + head, flush=True)
    env = {**os.environ, "FATWA_TEST_PG_BIN": pg_bin, "FATWA_RECOVERY_PG_BIN": pg_bin}
    stages = [
        ("system", ["manage.py", "check"]),
        ("drift", ["manage.py", "makemigrations", "--check", "--dry-run"]),
        ("scope-evidence", ["docs/product/v12_scope_evidence/build.py", "--check"]),
        ("scope-validator", ["-m", "unittest", "discover", "-s",
                             "docs/product/v12_scope_evidence", "-p", "test_*.py", "-v"]),
        ("affected", ["manage.py", "test", *LABELS, "--noinput", "--verbosity", "2"]),
    ]
    if args.browser:
        stages.append(("browser-recovery", ["manage.py", "test",
                      "tests.casework.test_v12_browser", "--noinput", "--verbosity", "2"]))
    for name, command in stages:
        with (logs / (name + ".log")).open("w", encoding="utf-8") as output:
            result = subprocess.run([sys.executable, *command], env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
        print(name.upper() + " EXIT=" + str(result.returncode), flush=True)
        print((logs / (name + ".log")).read_text(), flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
