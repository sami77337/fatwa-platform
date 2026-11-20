"""Real guarded runner creation/cleanup in separate owned PG17/18 databases.

The parent suite keeps its own database. Each probe creates a fresh auxiliary
base, then a child exercises the actual runner, migrations and ownership guards.
No guard, cursor, DROP, database identity or backend process is mocked.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.db.backends.signals import connection_created
from django.test import TransactionTestCase
from psycopg import sql

from apps.intake_workflow import guards

from .runner import Wave7TestRunner

PREFIX = "WAVE7_RUNNER_LIFECYCLE="


def session_settings():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_setting('statement_timeout'), current_setting('lock_timeout')"
        )
        return cursor.fetchone()


def database_oid(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT oid FROM pg_database WHERE datname=%s", [name])
        found = cursor.fetchone()
        return found[0] if found else None


class DropObserver:
    """Read actual server settings immediately before forwarding the real DROP."""

    def __init__(self):
        self.observed = []

    def __call__(self, execute, query, params, many, context):
        backend = context["connection"].connection
        statement = query.as_string(backend) if isinstance(query, sql.Composable) else query
        if statement.startswith("DROP DATABASE "):
            # A separate raw cursor on the same backend avoids recursive wrapper
            # instrumentation. Neither the statement nor its settings are changed.
            with backend.cursor() as cursor:
                cursor.execute(
                    "SELECT current_database(), current_setting('statement_timeout'), "
                    "current_setting('lock_timeout')"
                )
                self.observed.append(cursor.fetchone())
        return execute(query, params, many, context)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def lifecycle_probe(scenario):
    """Child entry: only its environment-selected owned base/test pair is used."""
    target = guards.validate_write_configuration(synthetic_fixtures_only=True)
    require(target.database_name == target.base_name, "probe must start from its owned base")
    guards.initialize_synthetic_database(synthetic_fixtures_only=True)
    call_command("migrate", verbosity=0, interactive=False, database="default")
    base = guards.require_synthetic_write(synthetic_fixtures_only=True)
    options = copy.deepcopy(connection.settings_dict["OPTIONS"])
    original_settings = session_settings()
    require(original_settings == ("3s", "3s"), "runtime query/lock budgets must remain 3s")
    owner = Wave7TestRunner(verbosity=0, interactive=False)
    blocker = None
    observer = DropObserver()
    result = {"scenario": scenario, "runtime_settings": original_settings}
    try:
        owner.setup_databases()
        created = guards.require_synthetic_write(synthetic_fixtures_only=True)
        require(created.database_name == target.test_name, "runner must own its actual test DB")
        require(owner._wave7_created == target.test_name, "creation receipt missing")

        if scenario == "success":
            # A real session initializer gives this maintenance connection a
            # different finite original value. Restoration must not hardcode 3s.
            def set_original(sender, connection, **kwargs):
                if connection.settings_dict["NAME"] == target.base_name:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('statement_timeout', '1709ms', false)")

            connection_created.connect(set_original, weak=False)
            try:
                with connection.execute_wrapper(observer):
                    owner._wave7_cleanup()
                require(
                    session_settings() == ("1709ms", "3s"), "original session value not restored"
                )
                result["restored_settings"] = session_settings()
            finally:
                connection_created.disconnect(set_original)
            require(owner._wave7_created is None, "successful cleanup must clear its receipt")
            require(database_oid(target.test_name) is None, "created test database still exists")
            result["created_database_removed"] = True

        elif scenario == "failure":
            # PostgreSQL itself refuses to drop a database with this live client.
            # The new maintenance budget permits its normal ObjectInUse result;
            # the old 3s statement budget instead cancels that DROP prematurely.
            blocker = psycopg.connect(**connection.get_connection_params(), autocommit=True)
            with blocker.cursor() as cursor:
                cursor.execute("SELECT current_database(), pg_backend_pid()")
                blocked_name, blocked_pid = cursor.fetchone()
            require(blocked_name == target.test_name, "blocker must use this invocation's DB")
            with connection.execute_wrapper(observer):
                try:
                    owner._wave7_cleanup()
                except DatabaseError as exc:
                    state = getattr(exc.__cause__, "sqlstate", None)
                    require(
                        state == "55006", "expected PostgreSQL ObjectInUse, not query cancellation"
                    )
                    result["failure_sqlstate"] = state
                else:
                    raise AssertionError("cleanup must not drop a database with a live client")
            require(session_settings() == original_settings, "failed DROP changed runtime timeout")
            require(owner._wave7_created == target.test_name, "failure lost the creation receipt")
            require(
                database_oid(target.test_name) == created.database_oid, "failed DROP replaced DB"
            )
            with blocker.cursor() as cursor:
                cursor.execute("SELECT current_database(), pg_backend_pid(), 73")
                require(
                    cursor.fetchone() == (target.test_name, blocked_pid, 73),
                    "cleanup must not terminate or replace the other live session",
                )
            result.update(restored_settings=session_settings(), live_client_preserved=True)
            blocker.close()
            blocker = None
            owner._wave7_cleanup()  # Release the known owner after the test client has closed.
            require(database_oid(target.test_name) is None, "owner cleanup did not complete")

        elif scenario == "ownership":
            connection.close()
            connection.settings_dict["NAME"] = target.base_name
            outsider = Wave7TestRunner(verbosity=0, interactive=False)
            with connection.execute_wrapper(observer):
                outsider._wave7_cleanup()  # No creation receipt: no cleanup authority.
                try:
                    outsider.setup_databases()
                except RuntimeError as exc:
                    require("pre-existing test database" in str(exc), "wrong creation refusal")
                else:
                    raise AssertionError("a second invocation must refuse the existing test DB")
                require(outsider._wave7_created is None, "outsider acquired an existing database")

                owner._wave7_created = target.base_name
                try:
                    try:
                        owner._wave7_cleanup()
                    except RuntimeError as exc:
                        require(
                            "exact-resource cleanup identity changed" in str(exc),
                            "wrong name refusal",
                        )
                    else:
                        raise AssertionError("cleanup must refuse its base as the claimed target")
                finally:
                    owner._wave7_created = target.test_name

                with patch.dict(os.environ, {"FATWA_WAVE7_SYNTHETIC_WRITES": "0"}):
                    try:
                        owner._wave7_cleanup()
                    except guards.SyntheticWriteDenied as exc:
                        require(exc.code == "WRITES_DISABLED", "wrong synthetic guard refusal")
                    else:
                        raise AssertionError("disabled synthetic writes must deny cleanup")
            require(observer.observed == [], "a refused invocation attempted a DROP")
            require(session_settings() == original_settings, "refusal changed session budgets")
            require(database_oid(target.base_name) == base.database_oid, "owned base changed")
            require(
                database_oid(target.test_name) == created.database_oid, "existing test DB changed"
            )
            result.update(
                no_receipt_no_drop=True,
                preexisting_refused=True,
                wrong_name_refused=True,
                disabled_write_refused=True,
                restored_settings=session_settings(),
            )
        else:
            raise AssertionError("unknown lifecycle scenario")

        require(
            connection.settings_dict["OPTIONS"] == options, "runtime connection options changed"
        )
        if scenario != "ownership":
            require(
                observer.observed == [(target.base_name, "30s", "3s")],
                "only the exact maintenance DROP may use the finite 30s statement budget",
            )
            result["drop_settings"] = observer.observed[0][1:]
        require(
            database_oid(target.base_name) == base.database_oid, "cleanup touched the owned base"
        )
    finally:
        if blocker is not None:
            blocker.close()
        owner._wave7_cleanup()
        connection.close()
    print(PREFIX + json.dumps(result, sort_keys=True), flush=True)


class RunnerLifecycleTests(TransactionTestCase):
    def probe(self, scenario):
        guards.require_synthetic_write(synthetic_fixtures_only=True)
        name = "wave7_synthetic_cleanup_" + uuid4().hex[:16]
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            env = dict(
                os.environ,
                PGDATABASE=name,
                PGTESTDATABASE="test_" + name,
                DJANGO_SETTINGS_MODULE="config.settings.wave7_test",
            )
            completed = subprocess.run(
                [sys.executable, "-m", __name__, "--probe", scenario],
                cwd=Path(__file__).resolve().parents[2],
                env=env,
                capture_output=True,
                text=True,
                timeout=55,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            evidence = [line for line in completed.stdout.splitlines() if line.startswith(PREFIX)]
            self.assertEqual(len(evidence), 1, completed.stdout)
            result = json.loads(evidence[0][len(PREFIX) :])
            self.assertEqual(result["scenario"], scenario)
            self.assertEqual(result["runtime_settings"], ["3s", "3s"])
            print(PREFIX + json.dumps(result, sort_keys=True), flush=True)
            return result
        finally:
            # This fixture created only this exact auxiliary base. It never
            # removes a test DB on behalf of a child that failed to prove ownership.
            guards.require_synthetic_write(synthetic_fixtures_only=True)
            with connection.cursor() as cursor:
                cursor.execute("SHOW statement_timeout")
                previous = cursor.fetchone()[0]
                try:
                    cursor.execute("SELECT set_config('statement_timeout', '30s', false)")
                    cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
                finally:
                    cursor.execute("SELECT set_config('statement_timeout', %s, false)", [previous])

    def test_success_drops_only_created_database_and_restores_actual_original_timeout(self):
        result = self.probe("success")
        self.assertTrue(result["created_database_removed"])
        self.assertEqual(result["drop_settings"], ["30s", "3s"])
        self.assertEqual(result["restored_settings"], ["1709ms", "3s"])

    def test_live_client_refusal_restores_timeouts_and_never_terminates_the_client(self):
        result = self.probe("failure")
        self.assertEqual(result["failure_sqlstate"], "55006")
        self.assertTrue(result["live_client_preserved"])
        self.assertEqual(result["drop_settings"], ["30s", "3s"])
        self.assertEqual(result["restored_settings"], ["3s", "3s"])

    def test_preexisting_wrong_name_or_disabled_write_never_acquires_cleanup_authority(self):
        result = self.probe("ownership")
        for key in (
            "no_receipt_no_drop",
            "preexisting_refused",
            "wrong_name_refused",
            "disabled_write_refused",
        ):
            self.assertTrue(result[key])
        self.assertEqual(result["restored_settings"], ["3s", "3s"])


if __name__ == "__main__":
    import django

    django.setup()
    if len(sys.argv) != 3 or sys.argv[1] != "--probe":
        raise SystemExit("Expected a guarded lifecycle probe scenario")
    lifecycle_probe(sys.argv[2])
