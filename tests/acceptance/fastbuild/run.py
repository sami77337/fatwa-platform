"""Run editorial without DB, or explicitly opt into the existing guarded PG lifecycle."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", action="store_true")
    args = parser.parse_args()
    os.environ["DJANGO_SETTINGS_MODULE"] = (
        "config.settings.wave7_test" if args.catalog else "config.settings.test"
    )
    import django

    django.setup()
    if args.catalog:
        from apps.intake_workflow.guards import SyntheticWriteDenied, require_synthetic_write
        from tests.acceptance.wave7.target import require_lane_configuration
        from tests.wave7_foundation.runner import Wave7TestRunner

        try:
            require_lane_configuration()
            require_synthetic_write(synthetic_fixtures_only=True)
        except SyntheticWriteDenied as error:
            # Emit the same complete NOT_RUN case inventory without contacting any service.
            return subprocess.run(
                [
                    "node",
                    str(Path(__file__).with_name("browser.mjs")),
                    "http://127.0.0.1:1",
                    "catalog",
                    "--not-run",
                    error.code,
                ],
                check=False,
                timeout=30,
            ).returncode
        runner = Wave7TestRunner
        label = "tests.acceptance.fastbuild.catalog_gate.CatalogBrowserTests"
    else:
        from django.test.runner import DiscoverRunner

        runner = DiscoverRunner
        label = "tests.acceptance.fastbuild.test_browser.EditorialBrowserTests"
    return int(bool(runner(verbosity=2, interactive=False).run_tests([label])))


if __name__ == "__main__":
    sys.exit(main())
