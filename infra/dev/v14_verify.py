"""Exact-head V14 affected verification on an explicitly owned PostgreSQL server.

The integrator supplies concrete lane test labels after their contracts land.
Missing applications, matrix or browser modules fail; they are never skipped into
a V14 completion claim. This command runs beneath with_casework_postgres.py.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

APPLICATIONS = (
    "browser_audio",
    "timed_citations",
    "pdf_citations",
    "arabic_search_eval",
    "classification_review",
)
SECURITY_LABEL = "tests.v14_security_review.test_search_boundary"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    if args.browser and os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
        parser.error("V14 browser evidence requires explicit FATWA_BROWSER_SANDBOX=1")
    if any(re.fullmatch(r"(?:apps|tests)\.[A-Za-z0-9_.]+", label) is None for label in args.label):
        parser.error("explicit Python application/test module labels required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != os.environ.get("EXPECTED_SHA", head):
        parser.error("checked-out SHA differs from EXPECTED_SHA")
    subprocess.run(["git", "diff", "HEAD", "--exit-code", "--quiet"], check=True)
    for name in APPLICATIONS:
        if not Path("apps", name, "__init__.py").is_file():
            parser.error("V14 composition incomplete: " + name)
    required = (
        "docs/product/v14_scope_evidence/build.py",
        "tests/v14_security_review/test_search_boundary.py",
        "tests/casework/test_v14_browser.py",
        "tests/casework/v14_restored_browser.py",
    )
    if any(not Path(name).is_file() for name in required):
        parser.error("V14 evidence/security/browser composition incomplete")
    pg_bin = str(args.pg_bin.resolve(strict=True))
    version = subprocess.check_output([str(Path(pg_bin) / "postgres"), "--version"], text=True)
    major = version.split()[2].split(".")[0]
    if major not in {"17", "18"}:
        parser.error("V14 requires PostgreSQL 17 or18")
    logs = Path(".local/qa/v14/pg" + major)
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "tested-sha.txt").write_text(head + "\n")
    receipt = {
        "tested_sha": head,
        "postgres": version.strip(),
        "bootstrap_settings": "config.settings.campaign_review",
        "runtime_guards": "explicit fixture initialization; strict V14 profile remains closed",
        "browser_requested": args.browser,
        "stages": [],
        "status": "RUNNING",
    }
    receipt_path = logs / "execution.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("TESTED_SHA=" + head, flush=True)
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.campaign_review",
           "V12_PG_BIN": pg_bin, "FATWA_TEST_PG_BIN": pg_bin,
           "FATWA_RECOVERY_PG_BIN": pg_bin, "FATWA_FASTBUILD_PYTHON": sys.executable}
    labels = list(dict.fromkeys([SECURITY_LABEL, *args.label]))
    stages = [
        ("system", ["manage.py", "check"]),
        ("drift", ["manage.py", "makemigrations", "--check", "--dry-run"]),
        ("scope-evidence", ["docs/product/v14_scope_evidence/build.py", "--check"]),
        ("scope-validator", ["-m", "unittest", "discover", "-s",
                             "docs/product/v14_scope_evidence", "-p", "test_*.py", "-v"]),
        ("affected", ["manage.py", "test", *labels, "--noinput", "--verbosity", "2"]),
    ]
    if args.browser:
        stages.append(("browser-recovery", ["manage.py", "test",
                       "tests.casework.test_v14_browser", "--noinput", "--verbosity", "2"]))
    stages = [(name, [sys.executable, *command]) for name, command in stages]
    for name, command in stages:
        path = logs / (name + ".log")
        if name == "browser-recovery":
            Path(".local/qa/v14/browser/result.json").unlink(missing_ok=True)
        with path.open("w", encoding="utf-8") as output:
            result = subprocess.run(command, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
        print(name.upper() + " EXIT=" + str(result.returncode), flush=True)
        print(path.read_text(), flush=True)
        receipt["stages"].append({"name": name, "exit_code": result.returncode})
        receipt["status"] = "FAILED" if result.returncode else "RUNNING"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        if result.returncode:
            return result.returncode
        if name == "browser-recovery":
            proof = json.loads(Path(".local/qa/v14/browser/result.json").read_text())
            if proof.get("status") != "PASS" or (
                env.get("FATWA_BROWSER_SANDBOX", "1") == "1"
                and proof.get("sandbox") is not True
            ):
                raise RuntimeError("V14 protected browser proof missing")
            print("V14_BROWSER_PROOF=" + json.dumps({
                "tested_sha": head, "browser": proof["browser"],
                "sandbox": proof["sandbox"], "widths": proof["widths"],
                "canonical": proof["canonical"], "recovery": proof["recovery"],
                "external_requests": len(proof["external_requests"]),
                "page_errors": len(proof["page_errors"]),
            }, sort_keys=True), flush=True)
    receipt["status"] = "PASS" if args.browser else "AFFECTED_CHECKS_ONLY"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
