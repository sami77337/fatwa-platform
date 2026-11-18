"""Exact-head V13 affected verification on an explicitly owned PostgreSQL server.

The integrator supplies concrete lane test labels after their contracts land.
Missing applications, matrix or browser modules fail; they are never skipped into
a V13 completion claim. This command runs beneath with_casework_postgres.py.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

APPLICATIONS = (
    "browser_audio",
    "timed_citations",
    "arabic_search_eval",
    "classification_review",
)
SECURITY_LABEL = "tests.v13_security_review.test_delta"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    if any(re.fullmatch(r"(?:apps|tests)\.[A-Za-z0-9_.]+", label) is None for label in args.label):
        parser.error("explicit Python application/test module labels required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != os.environ.get("EXPECTED_SHA", head):
        parser.error("checked-out SHA differs from EXPECTED_SHA")
    subprocess.run(["git", "diff", "HEAD", "--exit-code", "--quiet"], check=True)
    for name in APPLICATIONS:
        if not Path("apps", name, "__init__.py").is_file():
            parser.error("V13 composition incomplete: " + name)
    required = (
        "docs/product/v13_scope_evidence/build.py",
        "tests/v13_security_review/test_delta.py",
        "tests/casework/test_v13_browser.py",
        "tests/casework/v13_restored_browser.py",
    )
    if any(not Path(name).is_file() for name in required):
        parser.error("V13 evidence/security/browser composition incomplete")
    pg_bin = str(args.pg_bin.resolve(strict=True))
    version = subprocess.check_output([str(Path(pg_bin) / "postgres"), "--version"], text=True)
    major = version.split()[2].split(".")[0]
    if major not in {"17", "18"}:
        parser.error("V13 requires PostgreSQL 17 or18")
    logs = Path(".local/qa/v13/pg" + major)
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "tested-sha.txt").write_text(head + "\n")
    print("TESTED_SHA=" + head, flush=True)
    env = {**os.environ, "V12_PG_BIN": pg_bin, "FATWA_TEST_PG_BIN": pg_bin,
           "FATWA_RECOVERY_PG_BIN": pg_bin, "FATWA_FASTBUILD_PYTHON": sys.executable}
    labels = list(dict.fromkeys([SECURITY_LABEL, *args.label]))
    stages = [
        ("system", ["manage.py", "check"]),
        ("drift", ["manage.py", "makemigrations", "--check", "--dry-run"]),
        ("scope-evidence", ["docs/product/v13_scope_evidence/build.py", "--check"]),
        ("scope-validator", ["-m", "unittest", "discover", "-s",
                             "docs/product/v13_scope_evidence", "-p", "test_*.py", "-v"]),
        ("startup-evidence", ["-m", "unittest", "tests.v13_browser_startup.test_evidence", "-v"]),
        ("affected", ["manage.py", "test", *labels, "--noinput", "--verbosity", "2"]),
    ]
    if args.browser:
        stages.append(("browser-recovery", ["manage.py", "test",
                       "tests.casework.test_v13_browser", "--noinput", "--verbosity", "2"]))
    stages = [(name, [sys.executable, *command]) for name, command in stages]
    stages.insert(2, ("startup-lifecycle", [
        "node", "--test", "tests/v13_browser_startup/startup_contract.test.mjs",
                "tests/acceptance/fastbuild/v13_diagnostics.test.mjs",
    ]))
    for name, command in stages:
        path = logs / (name + ".log")
        with path.open("w", encoding="utf-8") as output:
            result = subprocess.run(command, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
        print(name.upper() + " EXIT=" + str(result.returncode), flush=True)
        print(path.read_text(), flush=True)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
