"""Django runner restricted to the B6 disposable synthetic PG17/18 service.

Only this runner may discover/run the acceptance module. Django performs its
existing migrations. Creation deliberately has NO Django autoclobber fallback:
an occupied name, including a create race, raises without DROP or reuse.
"""

import os
from contextlib import contextmanager
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
_created_oid = None


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
    if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE")):
        raise SyntheticGuardError("PostgreSQL target override forbidden")
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
        or db.get("OPTIONS")
        != {
            "connect_timeout": 5,
            "options": "-c statement_timeout=3000 -c lock_timeout=3000",
        }
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
    identity = {"database": name, "role": role, "server_version_num": int(version)}
    if database == TEST_DATABASE:
        identity["database_oid"] = require_created_oid(cursor)
    return identity


def target_oid(cursor):
    cursor.execute(
        "SELECT oid FROM pg_database WHERE datname = %s AND datdba = current_user::regrole",
        [TEST_DATABASE],
    )
    row = cursor.fetchone()
    if row is None or type(row[0]) is not int or row[0] <= 0:
        raise SyntheticGuardError("Owned synthetic test database not found")
    return row[0]


def require_created_oid(cursor):
    if _created_oid is None or target_oid(cursor) != _created_oid:
        raise SyntheticGuardError("Created synthetic database OID mismatch")
    return _created_oid


def require_unused(cursor):
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [TEST_DATABASE])
    if cursor.fetchone() is not None:
        raise SyntheticGuardError("Occupied synthetic test database; refusing reuse or deletion")


def create_without_reuse(verbosity, autoclobber, keepdb=False):
    global _created_oid
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
        _created_oid = target_oid(cursor)
    emit("created_unused_database", **identity, test_database=TEST_DATABASE, test_oid=_created_oid)
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
        global _running, _created_oid
        require_configuration()
        if _running:
            raise SyntheticGuardError("Synthetic database already in use by this runner")
        _created_oid = None
        revision_evidence()
        with connection.cursor() as cursor:
            identity = verify_identity(cursor, "b6_ephemeral")
            require_unused(cursor)
        emit("preflight_unused_database", **identity, test_database=TEST_DATABASE)
        # Replace only creation's unsafe retry path; migrations remain Django's.
        with patch.object(connection.creation, "_create_test_db", create_without_reuse):
            old_config = super().setup_databases(**kwargs)
        with connection.cursor() as cursor:
            verify_identity(cursor, TEST_DATABASE)
        _running = True
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
        global _running, _created_oid
        try:
            require_running_database()
            if old_config != [(connections["default"], "b6_ephemeral", True)]:
                raise SyntheticGuardError("Unexpected Django teardown target")
            maintenance_cursor = connection.creation._nodb_cursor

            @contextmanager
            def checked_cursor():
                with maintenance_cursor() as cursor:
                    verify_identity(cursor, "postgres")
                    require_created_oid(cursor)
                    yield cursor

            with patch.object(connection.creation, "_nodb_cursor", checked_cursor):
                super().teardown_databases(old_config, **kwargs)
        finally:
            _running = False
            _created_oid = None
            connections.close_all()
