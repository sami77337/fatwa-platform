"""Narrow the existing trusted Wave7 runner to this preauthorized synthetic target."""

BASE_DATABASE = "wave7_synthetic_fast9_reference"
TEST_DATABASE = "test_" + BASE_DATABASE
SETTINGS = "config.settings.wave7_test"
RUNNER = "tests.wave7_foundation.runner.Wave7TestRunner"
ACK = "FAST9_DISPOSABLE_SYNTHETIC_ONLY"


class PrerequisiteUnavailable(RuntimeError):
    pass


def validate_environment(environment):
    """Reject defaults and inherited overrides before Django or a driver is loaded."""
    expected = {
        "FAST9_PG_ACK": ACK,
        "FATWA_PRODUCTION": "0",
        "FATWA_WAVE7_SYNTHETIC_WRITES": "1",
        "PGHOST": "127.0.0.1",
        "PGUSER": "wave7_synthetic",
        "PGDATABASE": BASE_DATABASE,
        "PGTESTDATABASE": TEST_DATABASE,
        "DJANGO_SETTINGS_MODULE": SETTINGS,
    }
    if any(environment.get(key) != value for key, value in expected.items()):
        raise PrerequisiteUnavailable("EXPLICIT_SYNTHETIC_CONFIGURATION_REQUIRED")
    port = environment.get("PGPORT", "")
    if (
        not port.isascii()
        or not port.isdecimal()
        or not 1024 <= int(port) <= 65535
        or int(port) in (5432, 55432, 8000)
    ):
        raise PrerequisiteUnavailable("ISOLATED_EXPLICIT_PORT_REQUIRED")
    if any(
        environment.get(key)
        for key in (
            "DATABASE_URL",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGPASSFILE",
            "PGOPTIONS",
        )
    ):
        raise PrerequisiteUnavailable("CONNECTION_OVERRIDE_FORBIDDEN")
    if not environment.get("PGPASSWORD"):
        raise PrerequisiteUnavailable("EXPLICIT_SYNTHETIC_CREDENTIAL_REQUIRED")


def require_target(*, test_database: bool):
    import os

    validate_environment(os.environ)
    from django.conf import settings
    from django.db import connections

    from apps.intake_workflow.guards import require_owned_database, validate_write_configuration

    if settings.TEST_RUNNER != RUNNER:
        raise PrerequisiteUnavailable("TRUSTED_RUNNER_REQUIRED")
    name = TEST_DATABASE if test_database else BASE_DATABASE
    expected = {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "PORT": os.environ["PGPORT"],
        "USER": "wave7_synthetic",
        "NAME": name,
        "PASSWORD": os.environ["PGPASSWORD"],
    }
    # Django can cache a connection configured before opt-in. Bind both the
    # settings and effective wrapper to the explicit target before any query.
    for database in (settings.DATABASES.get("default", {}), connections["default"].settings_dict):
        if (
            any(str(database.get(key, "")) != value for key, value in expected.items())
            or database.get("TEST", {}).get("NAME") != TEST_DATABASE
        ):
            raise PrerequisiteUnavailable("EFFECTIVE_CONNECTION_MISMATCH")
    target = validate_write_configuration(synthetic_fixtures_only=True)
    if (
        target.database_name != name
        or target.base_name != BASE_DATABASE
        or target.test_name != TEST_DATABASE
    ):
        raise PrerequisiteUnavailable("EXACT_DATABASE_REQUIRED")
    # Existing guard verifies actual name, role, PG17/18, ownership marker and OID.
    # No initialization, credential lookup, discovery, or migrations here.
    return require_owned_database(synthetic_fixtures_only=True)
