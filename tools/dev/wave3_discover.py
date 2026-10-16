"""Standard-library unittest discovery with a fail-closed zero-test guard."""
import sys
import unittest
from pathlib import Path

# Python script entry points in tools/dev do not otherwise see project-root apps.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    suite = unittest.defaultTestLoader.discover(sys.argv[1], pattern="test*.py")
    if suite.countTestCases() == 0:
        print("NOT_RUN: unittest discovery collected zero tests", file=sys.stderr)
        return 2
    return int(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
