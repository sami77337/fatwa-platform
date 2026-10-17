"""Read-only Wave3 dispatcher. Missing integrated packages are NOT_RUN, never PASS."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

# Direct execution and unittest imports use the same existing safety boundary.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("content_intake", "fatwa_drafts", "reference_links", "fiqh_import")


def dispatch(*, standalone=False, require_integrated=False, reports=None):
    report = {"gates": "NOT_DEPLOYED / GATES_HOLD",
              "source_acceptance": "NOT_RUN", "postgres": "NOT_RUN: no database actions"}
    failed = False
    try:
        if sys.version_info[:2] != (3, 13):
            raise RuntimeError("Python 3.13 required")
        report.update(qa.committed())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        report["preflight"] = "FAIL: " + type(exc).__name__
        return 1, report

    if reports is not None:
        reports.mkdir(parents=True, exist_ok=True)

    def execute(name, command):
        nonlocal failed
        try:
            qa.run(command)
            report[name] = "PASS"
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            report[name] = "FAIL: " + type(exc).__name__
            failed = True

    for package in PACKAGES:
        directory = ROOT / "tests" / package
        if not directory.is_dir() or not any(directory.rglob("test*.py")):
            report[package] = "NOT_RUN: test package absent or empty"
            failed |= require_integrated
            continue
        # Explicit start directories work with Python 3.13 namespace-only tests/.
        command = [sys.executable, "tools/dev/wave3_discover.py", "tests/" + package]
        if reports is not None:
            command.extend(["--json", str(reports / (package + ".json"))])
        execute(package, command)
    if not standalone:
        execute("dispatcher_tests", [sys.executable, "-m", "unittest", "discover",
                                     "-s", "tests/dev", "-p", "test_*.py", "-v"])
        execute("django", [sys.executable, "manage.py", "check",
                           "--settings=config.settings.test"])
        try:
            qa.node()
            report["node"] = "PASS"
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            report["node"] = "FAIL: " + type(exc).__name__
            failed = True
    return int(failed), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standalone", action="store_true")
    parser.add_argument("--require-integrated", action="store_true",
                        help="Fail when any required pure/importer package is absent (CI default)")
    parser.add_argument("--reports", type=Path, help="Save per-package counts, inventory and skips")
    args = parser.parse_args()
    code, report = dispatch(standalone=args.standalone,
                            require_integrated=args.require_integrated, reports=args.reports)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
