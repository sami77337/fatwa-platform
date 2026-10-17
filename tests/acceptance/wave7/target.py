"""E6 test resource selection. Actual ownership/write policy remains E5's guard."""
import os


def require_lane_configuration():
    from apps.intake_workflow.guards import SyntheticWriteDenied, validate_write_configuration
    if os.environ.get("FATWA_WAVE7_E6_ACCEPTANCE") != "1":
        raise SyntheticWriteDenied("E6_ACCEPTANCE_OPT_IN_REQUIRED")
    target = validate_write_configuration(synthetic_fixtures_only=True)
    if not target.base_name.startswith("wave7_synthetic_e6_"):
        raise SyntheticWriteDenied("E6_DEDICATED_DATABASE_REQUIRED")
    return target


def select_existing_test_database():
    """Child process only: select the runner-created test target, never create/reset."""
    from django.db import connections
    from apps.intake_workflow.guards import require_synthetic_write, SyntheticWriteDenied
    target = require_lane_configuration()
    connection = connections["default"]
    connection.close()
    connection.settings_dict["NAME"] = target.test_name
    context = require_synthetic_write(synthetic_fixtures_only=True)
    if context.database_name != target.test_name:
        raise SyntheticWriteDenied("E6_TEST_DATABASE_REQUIRED")
    return context
