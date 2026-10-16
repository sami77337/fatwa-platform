"""Run from repo root: .venv/bin/python tests/acceptance/wave6/run.py [--browser]."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--browser", action="store_true")
    group.add_argument("--regressions", action="store_true")
    group.add_argument("--assets", action="store_true")
    parser.add_argument("--review-batches", action="store_true",
                        help="Require PR51 batch hooks; combine with --browser for real browser integration")
    args = parser.parse_args()
    if args.review_batches and (args.assets or args.regressions):
        parser.error("--review-batches cannot be combined with --assets or --regressions")
    if args.review_batches:
        os.environ["E6_REVIEW_BATCHES"] = "required"
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("E6 requires Python 3.13")
    # Guard BEFORE Django test runner can create/drop a database. No --keepdb or fallback.
    from support import require_disposable_database
    require_disposable_database()
    import django
    django.setup()
    from django.test.runner import DiscoverRunner
    label = ("test_browser" if args.browser else "test_regressions" if args.regressions
             else "test_assets" if args.assets else "test_review_batches" if args.review_batches
             else "test_service")
    failures = DiscoverRunner(verbosity=2, interactive=False).run_tests([
        f"tests.acceptance.wave6.{label}"
    ])
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
