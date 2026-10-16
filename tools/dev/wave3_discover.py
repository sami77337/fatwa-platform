"""Unittest discovery with module inventory, zero-case guards and bounded evidence."""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = 0

    def addSuccess(self, test):
        self.passed += 1
        super().addSuccess(test)


def collect(folder):
    folder = folder.resolve()
    files = sorted(folder.rglob("test*.py")) if folder.is_dir() else []
    if len(files) > 1000:
        raise ValueError("test module inventory exceeds 1000")
    inventory = {str(path.relative_to(folder)).replace("\\", "/"): 0 for path in files}
    suite = unittest.defaultTestLoader.discover(str(folder), pattern="test*.py")
    for test in cases(suite):
        module = sys.modules.get(type(test).__module__)
        source = getattr(module, "__file__", None)
        if source:
            path = Path(source).resolve()
            if path.is_relative_to(folder):
                name = path.relative_to(folder).as_posix()
                if name in inventory:
                    inventory[name] += 1
    return suite, inventory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--json", type=Path, help="Bounded case/module/skip evidence")
    args = parser.parse_args(argv)
    report = {"status": "FAIL", "source_acceptance": "NOT_RUN",
              "gates": "NOT_DEPLOYED / GATES_HOLD", "modules": {},
              "uncollected_modules": [], "python": sys.version.split()[0]}
    code = 1
    try:
        identity = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=10, check=False)
        report["sha"] = identity.stdout.strip() if identity.returncode == 0 else None
        state = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"],
                               cwd=ROOT, capture_output=True, timeout=10, check=False)
        report["working_tree"] = ("DIRTY" if state.stdout else "CLEAN") if state.returncode == 0 else "UNAVAILABLE"
        suite, inventory = collect(args.folder)
        count = suite.countTestCases()
        missing = sorted(name for name, count in inventory.items() if not count)
        report.update(modules=inventory, uncollected_modules=missing)
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
        report["counts"] = {
            "collected": count, "run": result.testsRun, "passed": result.passed,
            "failures": len(result.failures), "errors": len(result.errors),
            "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
            "unexpected_successes": len(result.unexpectedSuccesses),
        }
        report["skips"] = [{"test": test.id()[:240], "reason": str(reason)[:240]}
                           for test, reason in result.skipped[:100]]
        report["skips_omitted"] = max(0, len(result.skipped) - 100)
        code = 2 if not count else int(not result.wasSuccessful() or bool(missing))
        if not count or missing:
            print("FAIL: zero cases or uncollected test modules: " +
                  ", ".join(missing)[:2000], file=sys.stderr)
        report["status"] = "PASS" if code == 0 else "FAIL"
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
        report["reason"] = type(exc).__name__
    serialized = json.dumps(report, ensure_ascii=True, indent=2)
    print(serialized)
    if args.json:
        try:
            args.json.write_text(serialized + "\n", encoding="utf-8")
        except OSError:
            return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())
