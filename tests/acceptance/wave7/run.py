"""Guarded E6 labels; shared Wave7 runner owns test database creation/cleanup."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.wave7_test"

LABELS = {
    "service": ["tests.acceptance.wave7.test_storage", "tests.acceptance.wave7.test_assets"],
    "browser-baseline": ["tests.acceptance.wave7.test_browser.BrowserBaselineTests"],
    "browser": ["tests.acceptance.wave7.test_browser.PersistedWorkflowBrowserTests"],
    "workflow-service": ["tests.acceptance.wave7.test_workflow_services"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=LABELS, required=True)
    parser.add_argument("--initialize-empty-base", action="store_true",
                        help="Explicitly claim only an empty isolated E6 base using E5 initializer")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Python 3.13 required")
    from target import require_lane_configuration
    require_lane_configuration()  # configuration denial before driver/transaction/test lifecycle
    import django
    django.setup()
    from apps.intake_workflow.guards import initialize_synthetic_database, require_synthetic_write
    from django.core.management import call_command
    if args.initialize_empty_base:
        initialize_synthetic_database(synthetic_fixtures_only=True)
        call_command("migrate", interactive=False, verbosity=1)
    require_synthetic_write(synthetic_fixtures_only=True)
    from tests.wave7_foundation.runner import Wave7TestRunner
    # Explicit labels: never assume E6 is discovered by existing foundation CI.
    return int(bool(Wave7TestRunner(verbosity=2, interactive=False).run_tests(LABELS[args.suite])))


if __name__ == "__main__":
    from apps.intake_workflow.guards import SyntheticWriteDenied
    try:
        sys.exit(main())
    except SyntheticWriteDenied as error:
        print(json.dumps({"result": "DENIED", "code": error.code}), file=sys.stderr)
        sys.exit(2)
