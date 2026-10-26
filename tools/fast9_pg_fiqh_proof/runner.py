"""Django runner restricted to the B6 disposable synthetic PG17/18 service.

Only this runner may discover/run the acceptance module. Django performs its
existing migrations. Creation deliberately has NO Django autoclobber fallback:
an occupied name, including a create race, raises without DROP or reuse.
"""

import os
from unittest.mock import patch

from django.conf import settings
from django.db import connection, connections
from django.test.runner import DiscoverRunner

from .proof import checked_fixture, emit, revision_evidence

TEST_DATABASE = "test_fast8_fiqh_navigation_synthetic"
LABEL = "tests.fast9_pg_fiqh_proof.postgresql"
EXPECTED_CASES = 8
_discovering = False
_running = False


class SyntheticGuardError(RuntimeError):
    pass


def require_configuration():
    expected = {
        "FAST9_PG_FIQH_SYNTHETIC_ONLY": "1",
        "FATWA_PRODUCTION": "0",
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "PGHOST": "127.0.0.1",
        "PGPORT": "5432",
        "PGUSER": "fatwa_ci",
        "PGDATABASE": "b6_ephemeral",
        "PGTESTDATABASE": TEST_DATABASE,
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise SyntheticGuardError("Explicit B6 disposable synthetic configuration required")
    if os.environ.get("EXPECTED_PG_MAJOR") not in {"17", "18"}:
        raise SyntheticGuardError("Explicit PostgreSQL 17/18 identity required")
    db = connection.settings_dict
    if (
        connection.vendor != "postgresql"
        or set(settings.DATABASES) != {"default"}
        or settings.DATABASE_ROUTERS
        or db["ENGINE"] != "django.db.backends.postgresql"
        or any(
            db[key] != value
            for key, value in {
                "HOST": "127.0.0.1",
                "PORT": "5432",
                "USER": "fatwa_ci",
            }.items()
        )
        or db["NAME"] not in {"b6_ephemeral", TEST_DATABASE}
        or db["TEST"]["NAME"] != TEST_DATABASE
        or db["TEST"].get("MIRROR")
    ):
        raise SyntheticGuardError("Dedicated synthetic PostgreSQL test database required")


def require_discovery():
    require_configuration()
    if not _discovering:
        raise SyntheticGuardError("Use the trusted SyntheticRunner before database setup")


def verify_identity(cursor, database):
    cursor.execute("SELECT current_database(), current_user, current_setting('server_version_num')")
    name, role, version = cursor.fetchone()
    if (
        name != database
        or role != "fatwa_ci"
        or int(version) // 10000 != int(os.environ["EXPECTED_PG_MAJOR"])
    ):
        raise SyntheticGuardError("Live synthetic PostgreSQL identity mismatch")
    return {"database": name, "role": role, "server_version_num": int(version)}


def require_unused(cursor):
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [TEST_DATABASE])
    if cursor.fetchone() is not None:
        raise SyntheticGuardError("Occupied synthetic test database; refusing reuse or deletion")


def create_without_reuse(verbosity, autoclobber, keepdb=False):
    require_configuration()
    if keepdb or connection.settings_dict["NAME"] != "b6_ephemeral":
        raise SyntheticGuardError("Fresh synthetic creation only")
    creation = connection.creation
    # Use Django's maintenance connection, but forbid its fallback to another DB.
    with creation._nodb_cursor() as cursor:
        identity = verify_identity(cursor, "postgres")
        require_unused(cursor)
        # The name is a constant; no caller-supplied SQL identifiers or suffixes.
        # A duplicate-name race propagates. Never call the base retry/drop path.
        cursor.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    emit("created_unused_database", **identity, test_database=TEST_DATABASE)
    # Verify the actual new connection before Django records/applies migrations.
    probe = connection.copy(alias="fast9_creation_probe")
    probe.settings_dict["NAME"] = TEST_DATABASE
    try:
        with probe.cursor() as cursor:
            emit("before_migrations", **verify_identity(cursor, TEST_DATABASE))
    finally:
        probe.close()
    return TEST_DATABASE


def require_running_database():
    require_configuration()
    if not _running or connection.settings_dict["NAME"] != TEST_DATABASE:
        raise SyntheticGuardError("Only the trusted synthetic runner may write fixtures")
    with connection.cursor() as cursor:
        return verify_identity(cursor, TEST_DATABASE)


class SyntheticRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        require_configuration()
        if connection.settings_dict["NAME"] != "b6_ephemeral":
            raise SyntheticGuardError("Cannot start on an existing test database")
        super().__init__(*args, **kwargs)
        if (
            self.keepdb
            or self.parallel != 0
            or self.test_name_patterns
            or self.tags
            or self.exclude_tags
        ):
            raise SyntheticGuardError("Full serial suite required; no keepdb or selection filters")

    def build_suite(self, test_labels=None, **kwargs):
        global _discovering
        require_configuration()
        if list(test_labels or []) != [LABEL]:
            raise SyntheticGuardError("Exact explicit FAST9 PostgreSQL module required")
        checked_fixture()
        _discovering = True
        try:
            suite = super().build_suite(test_labels, **kwargs)
        finally:
            _discovering = False
        if suite.countTestCases() != EXPECTED_CASES:
            raise SyntheticGuardError("Incomplete synthetic acceptance collection")
        return suite

    def setup_databases(self, **kwargs):
        global _running
        require_configuration()
        revision_evidence()
        with connection.cursor() as cursor:
            identity = verify_identity(cursor, "b6_ephemeral")
            require_unused(cursor)
        emit("preflight_unused_database", **identity, test_database=TEST_DATABASE)
        # Replace only creation's unsafe retry path; migrations remain Django's.
        with patch.object(connection.creation, "_create_test_db", create_without_reuse):
            old_config = super().setup_databases(**kwargs)
        _running = True
        require_running_database()
        return old_config

    def run_suite(self, suite, **kwargs):
        result = super().run_suite(suite, **kwargs)
        if result.testsRun != EXPECTED_CASES or result.skipped or result.expectedFailures:
            raise SyntheticGuardError("Acceptance requires every case with zero skips/xfails")
        emit(
            "result",
            tests=result.testsRun,
            failures=len(result.failures),
            errors=len(result.errors),
            skips=len(result.skipped),
            status="PASS_SYNTHETIC_ONLY" if result.wasSuccessful() else "FAIL",
        )
        return result

    def teardown_databases(self, old_config, **kwargs):
        global _running
        try:
            # Recheck before Django drops only the database created in this run.
            require_running_database()
            super().teardown_databases(old_config, **kwargs)
        finally:
            _running = False
            connections.close_all()
