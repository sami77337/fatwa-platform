"""SELECT-only evidence around the existing trusted Wave7 test lifecycle."""

import hashlib
import json
from contextlib import contextmanager

BASE = "wave7_synthetic_fast9_browser_ci"
TEST = "test_" + BASE
SETTINGS = "config.settings.wave7_test"
ACK = "FAST9_DISPOSABLE_DATABASE"


class NotRun(RuntimeError):
    """Fixed safe diagnostic; never include connection details."""


def authorize(env):
    """No Django import/connection until every explicit opt-in has matched."""
    required = {
        "FAST9_SYNTHETIC_PG": "1",
        ACK: TEST,
        "CI": "true",
        "FATWA_PRODUCTION": "0",
        "FATWA_WAVE7_SYNTHETIC_WRITES": "1",
        "PGHOST": "127.0.0.1",
        "PGUSER": "wave7_synthetic",
        "PGDATABASE": BASE,
        "PGTESTDATABASE": TEST,
        "DJANGO_SETTINGS_MODULE": SETTINGS,
    }
    if any(env.get(key) != value for key, value in required.items()):
        raise NotRun("EXACT_DISPOSABLE_CI_AUTHORIZATION_REQUIRED")
    if any(
        env.get(key)
        for key in (
            "DATABASE_URL",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGPASSFILE",
            "PGOPTIONS",
        )
    ):
        raise NotRun("CONNECTION_OVERRIDE_FORBIDDEN")
    port = env.get("PGPORT", "")
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise NotRun("EXPLICIT_PORT_REQUIRED")


def identity(expected):
    from django.db import connection

    from apps.intake_workflow.guards import require_owned_database, validate_write_configuration

    target = validate_write_configuration(synthetic_fixtures_only=True)
    if (target.database_name, target.base_name, target.test_name) != (expected, BASE, TEST):
        raise NotRun("CONFIGURED_DATABASE_IDENTITY_MISMATCH")
    context = require_owned_database(synthetic_fixtures_only=True)
    if context.database_name != expected:
        raise NotRun("ACTUAL_DATABASE_IDENTITY_MISMATCH")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
        if cursor.fetchone() != (0,):
            raise NotRun("DATABASE_NOT_EXCLUSIVE")
    return context


def empty_application():
    """After trusted migrations, all seven domain tables must still be empty."""
    from django.apps import apps
    from django.db import connection
    from django.db.models import AutoField

    models = [
        model
        for label in ("reference", "intake_workflow")
        for model in apps.get_app_config(label).get_models()
    ]
    tables = {model._meta.db_table for model in models} | {
        "django_migrations",
        "wave7_synthetic_ownership",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname NOT IN "
            "('public','pg_catalog','pg_toast','information_schema') "
            "AND nspname !~ '^pg_(toast_)?temp_[0-9]+$'"
        )
        if cursor.fetchall():
            raise NotRun("UNKNOWN_DATABASE_SCHEMA")
        cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p','v','m','f','S')"
        )
        sequences = {
            model._meta.db_table + "_id_seq"
            for model in models
            if isinstance(model._meta.pk, AutoField)
        } | {"django_migrations_id_seq"}
        if {row[0] for row in cursor.fetchall()} != tables | sequences:
            raise NotRun("UNKNOWN_DATABASE_RELATIONS")
    for model in models:
        if model.objects.exists():
            raise NotRun("APPLICATION_DATABASE_NOT_EMPTY")


def vacant_test_name():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", [TEST])
        if cursor.fetchone() is not None:
            raise NotRun("PREEXISTING_TEST_DATABASE_FORBIDDEN")


def fingerprint():
    """All public table rows (including timestamps), sequences and schema metadata.

    Called only after ownership + exact empty synthetic inventory checks. No
    private values are emitted: only a digest is returned. Reads are bounded by
    the inherited statement timeout and the tiny trusted fixture inventory.
    """
    from django.db import connection
    from psycopg import sql

    evidence = []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND c.relkind IN ('r','p','S') ORDER BY c.relname"
        )
        relations = cursor.fetchall()
        for name, kind in relations:
            cursor.execute(
                sql.SQL("SELECT row_to_json(t)::text FROM {}.{} t").format(
                    sql.Identifier("public"), sql.Identifier(name)
                )
            )
            evidence.append((name, kind, sorted(row[0] for row in cursor.fetchall())))
        for query in (
            "SELECT table_name,column_name,ordinal_position,column_default,is_nullable,data_type "
            "FROM information_schema.columns WHERE table_schema='public' ORDER BY 1,3",
            "SELECT c.relname,pg_get_constraintdef(k.oid) FROM pg_constraint k "
            "JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' ORDER BY 1,2",
            "SELECT c.relname,pg_get_triggerdef(t.oid) FROM pg_trigger t "
            "JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' ORDER BY 1,2",
        ):
            cursor.execute(query)
            evidence.append(cursor.fetchall())
    return hashlib.sha256(json.dumps(evidence, ensure_ascii=True).encode()).hexdigest()


def assert_unchanged(before, after):
    if before != after:
        raise AssertionError("DATABASE_CHANGED_DURING_BROWSER_JOURNEY")


@contextmanager
def read_only_connections():
    """Every WSGI connection must select the owned test DB and enforce read-only."""
    from django.db import connections
    from django.db.backends.signals import connection_created

    def protect(sender, connection, **kwargs):
        if connection.alias != "default" or connection.settings_dict["NAME"] != TEST:
            connection.close()
            raise AssertionError("BROWSER_DATABASE_IDENTITY_MISMATCH")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(),current_user")
            if cursor.fetchone() != (TEST, "wave7_synthetic"):
                raise AssertionError("BROWSER_DATABASE_IDENTITY_MISMATCH")
            cursor.execute("SET default_transaction_read_only = on")
            cursor.execute("SHOW default_transaction_read_only")
            if cursor.fetchone() != ("on",):
                raise AssertionError("BROWSER_READ_ONLY_REQUIRED")

    connections.close_all()
    connection_created.connect(protect, weak=False)
    try:
        yield
    finally:
        connection_created.disconnect(protect)
        connections.close_all()


def verify_dropped():
    from django.db import connection

    identity(BASE)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", [TEST])
        if cursor.fetchone() is not None:
            raise AssertionError("TEST_DATABASE_TEARDOWN_FAILED")
