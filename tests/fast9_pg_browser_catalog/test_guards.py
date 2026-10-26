import json
import os
import unittest
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.fast9_pg_browser_catalog import database as db
from tools.fast9_pg_browser_catalog.run import aggregate, decode, run


def authorized():
    return {
        "FAST9_SYNTHETIC_PG": "1",
        db.ACK: db.TEST,
        "CI": "true",
        "FATWA_PRODUCTION": "0",
        "FATWA_WAVE7_SYNTHETIC_WRITES": "1",
        "PGHOST": "127.0.0.1",
        "PGUSER": "wave7_synthetic",
        "PGDATABASE": db.BASE,
        "PGTESTDATABASE": db.TEST,
        "DJANGO_SETTINGS_MODULE": db.SETTINGS,
        "PGPORT": "55439",
    }


class AuthorizationTests(unittest.TestCase):
    def test_exact_opt_in(self):
        db.authorize(authorized())

    def test_each_missing_authorization_is_denied(self):
        for key in authorized():
            with self.subTest(key=key):
                env = authorized()
                del env[key]
                with self.assertRaises(db.NotRun):
                    db.authorize(env)

    def test_live_remote_or_other_test_identity_denied(self):
        for key, value in (
            ("PGDATABASE", "fatwa_reference_dev"),
            ("PGTESTDATABASE", "test_other"),
            (db.ACK, db.BASE),
            ("PGHOST", "localhost"),
            ("PGHOST", "203.0.113.1"),
            ("PGUSER", "postgres"),
            ("CI", "false"),
            ("FATWA_PRODUCTION", "1"),
            ("DJANGO_SETTINGS_MODULE", "config.settings.development"),
            ("PGPORT", "0"),
            ("PGPORT", "65536"),
            ("PGPORT", "١٢٣"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(db.NotRun):
                db.authorize({**authorized(), key: value})

    def test_connection_overrides_denied(self):
        for key in (
            "DATABASE_URL",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGHOSTADDR",
            "PGPASSFILE",
            "PGOPTIONS",
        ):
            with self.subTest(key=key), self.assertRaises(db.NotRun):
                db.authorize({**authorized(), key: "forbidden"})

    def test_cli_without_authorization_never_imports_or_starts_postgres(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "tools.fast9_pg_browser_catalog.run.subprocess.check_output",
                side_effect=["a" * 40, ""],
            ),
            patch("tools.fast9_pg_browser_catalog.run.postgres") as postgres,
        ):
            result = run(True)
        postgres.assert_not_called()
        self.assertEqual(result["result"], "NOT_RUN")
        self.assertEqual(result["catalog"], "NOT_RUN")


class ResultTests(unittest.TestCase):
    def test_browser_only_never_full_pass(self):
        self.assertEqual(aggregate({"browser": "PASS", "catalog": "NOT_RUN"}), "NOT_RUN")

    def test_every_required_stage_and_cleanup_must_pass(self):
        complete = dict.fromkeys(("browser", "catalog", "database_unchanged", "teardown"), "PASS")
        self.assertEqual(aggregate(complete), "PASS")
        for key in complete:
            with self.subTest(key=key):
                self.assertEqual(aggregate({**complete, key: "FAIL"}), "FAIL")
                self.assertEqual(aggregate({**complete, key: "NOT_RUN"}), "NOT_RUN")
                self.assertEqual(aggregate({**complete, key: "READY"}), "NOT_RUN")

    def test_protocol_rejects_missing_cleanup_and_exit_disagreement(self):
        for code, report in (
            (0, {"result": "PASS", "browser": "PASS"}),
            (1, {"result": "PASS", "browser": "PASS", "cleanup": {"result": "PASS"}}),
            (0, {"result": "PASS", "browser": "PASS", "cleanup": {"result": "FAIL"}}),
            (2, {"result": "UNKNOWN"}),
            (
                1,
                {
                    "result": "FAIL",
                    "browser": "PASS",
                    "catalog": {"result": "PASS"},
                    "cleanup": {"result": "PASS"},
                },
            ),
            (
                0,
                {
                    "result": "PASS",
                    "browser": "PASS",
                    "catalog": {"result": "NOT_RUN"},
                    "cleanup": {"result": "PASS"},
                },
            ),
        ):
            with self.subTest(code=code, report=report):
                self.assertEqual(
                    decode(SimpleNamespace(returncode=code, stdout=json.dumps(report)))["browser"],
                    "FAIL",
                )

    def test_malformed_protocol_is_failure(self):
        for data in ("", "[]", "null", "not json", '{"result": "PASS"}'):
            with self.subTest(data=data):
                self.assertEqual(
                    decode(SimpleNamespace(returncode=0, stdout=data))["browser"], "FAIL"
                )

    def test_changed_rows_sequences_or_timestamps_fail(self):
        with self.assertRaisesRegex(AssertionError, "DATABASE_CHANGED"):
            db.assert_unchanged("before", "after")


class LifecycleTests(unittest.TestCase):
    """Control-flow fault injection only; not PostgreSQL acceptance."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
        import django

        django.setup()

    def test_untrusted_database_never_reaches_runner_or_seed(self):
        from tools.fast9_pg_browser_catalog.run import postgres

        with (
            patch.object(db, "identity", side_effect=db.NotRun("UNTRUSTED")),
            patch("tests.wave7_foundation.runner.Wave7TestRunner.setup_databases") as setup,
            patch("apps.intake_workflow.fixtures.seed_reference_catalog") as seed,
        ):
            report = {}
            postgres(report)
        setup.assert_not_called()
        seed.assert_not_called()
        self.assertEqual(report["catalog"], "NOT_RUN")

    def test_occupied_application_never_creates_test_database(self):
        from tools.fast9_pg_browser_catalog.run import postgres

        with (
            patch.object(db, "identity"),
            patch.object(
                db, "empty_application", side_effect=db.NotRun("APPLICATION_DATABASE_NOT_EMPTY")
            ),
            patch("tests.wave7_foundation.runner.Wave7TestRunner.setup_databases") as setup,
        ):
            report = {}
            postgres(report)
        setup.assert_not_called()
        self.assertEqual(report["catalog"], "NOT_RUN")

    def test_preexisting_test_database_not_reused(self):
        cursor = Mock()
        cursor.fetchone.return_value = (1,)
        with patch("django.db.connection.cursor") as context:
            context.return_value.__enter__.return_value = cursor
            with self.assertRaisesRegex(db.NotRun, "PREEXISTING"):
                db.vacant_test_name()
        self.assertEqual(cursor.execute.call_args.args[1], [db.TEST])

    def test_unknown_relations_rejected_before_reading_rows(self):
        cursor = Mock()
        cursor.fetchall.side_effect = [[], [("private_unexpected",)]]
        fake_model = Mock()
        fake_model._meta.db_table = "reference_referencework"
        with (
            patch("django.db.connection.cursor") as context,
            patch("django.apps.apps.get_app_config") as app,
        ):
            context.return_value.__enter__.return_value = cursor
            app.return_value.get_models.return_value = [fake_model]
            with self.assertRaisesRegex(db.NotRun, "UNKNOWN_DATABASE_RELATIONS"):
                db.empty_application()
        fake_model.objects.exists.assert_not_called()

    @patch(
        "apps.intake_workflow.guards.validate_write_configuration",
        return_value=SimpleNamespace(database_name=db.TEST, base_name=db.BASE, test_name=db.TEST),
    )
    def test_wrong_actual_identity_and_concurrent_connection_rejected(self, validate):
        with patch(
            "apps.intake_workflow.guards.require_owned_database",
            return_value=SimpleNamespace(database_name="wrong"),
        ):
            with self.assertRaisesRegex(db.NotRun, "IDENTITY"):
                db.identity(db.TEST)
        cursor = Mock()
        cursor.fetchone.return_value = (1,)
        with (
            patch(
                "apps.intake_workflow.guards.require_owned_database",
                return_value=SimpleNamespace(database_name=db.TEST),
            ),
            patch("django.db.connection.cursor") as context,
        ):
            context.return_value.__enter__.return_value = cursor
            with self.assertRaisesRegex(db.NotRun, "EXCLUSIVE"):
                db.identity(db.TEST)

    def test_wrong_configured_database_denied_before_connect(self):
        with (
            patch(
                "apps.intake_workflow.guards.validate_write_configuration",
                return_value=SimpleNamespace(
                    database_name="wave7_synthetic_other", base_name=db.BASE, test_name=db.TEST
                ),
            ),
            patch("apps.intake_workflow.guards.require_owned_database") as connect,
        ):
            with self.assertRaisesRegex(db.NotRun, "CONFIGURED_DATABASE"):
                db.identity(db.TEST)
        connect.assert_not_called()

    def test_unknown_schema_denied_before_reading_relations(self):
        cursor = Mock()
        cursor.fetchall.return_value = [("unexpected",)]
        with (
            patch("django.db.connection.cursor") as context,
            patch("django.apps.apps.get_app_config") as app,
        ):
            context.return_value.__enter__.return_value = cursor
            app.return_value.get_models.return_value = []
            with self.assertRaisesRegex(db.NotRun, "UNKNOWN_DATABASE_SCHEMA"):
                db.empty_application()
        self.assertEqual(cursor.execute.call_count, 1)

    def test_actual_model_inventory_accepts_uuid_tables_without_sequences(self):
        from django.conf import settings
        from django.test import override_settings

        relations = [
            "reference_referencework",
            "reference_referenceedition",
            "reference_referenceheading",
            "reference_referencework_id_seq",
            "reference_referenceedition_id_seq",
            "reference_referenceheading_id_seq",
            "intake_workflow_intakebatch",
            "intake_workflow_intakeitem",
            "intake_workflow_intakereference",
            "intake_workflow_reviewevent",
            "django_migrations",
            "django_migrations_id_seq",
            "wave7_synthetic_ownership",
        ]
        with (
            override_settings(
                INSTALLED_APPS=[
                    *settings.INSTALLED_APPS,
                    "apps.intake_workflow.apps.IntakeWorkflowConfig",
                ]
            ),
            patch("django.db.connection.cursor") as context,
            patch("django.db.models.query.QuerySet.exists", return_value=False) as exists,
        ):
            cursor = Mock()
            context.return_value.__enter__.return_value = cursor
            cursor.fetchall.side_effect = [[], [(name,) for name in relations]]
            db.empty_application()
            self.assertEqual(exists.call_count, 7)
            cursor.fetchall.side_effect = [
                [],
                [(name,) for name in [*relations, "intake_workflow_intakebatch_id_seq"]],
            ]
            with self.assertRaisesRegex(db.NotRun, "UNKNOWN_DATABASE_RELATIONS"):
                db.empty_application()

    def fault_scenario(self, *, browser_error=False, changed=False, cleanup_error=False):
        from tools.fast9_pg_browser_catalog.run import postgres

        runner = Mock(_wave7_created=db.TEST)
        runner.setup_databases.return_value = ["created-by-trusted-runner"]
        if cleanup_error:
            runner.teardown_databases.side_effect = RuntimeError("deliberate failure")
        with ExitStack() as stack:
            stack.enter_context(
                patch("tests.wave7_foundation.runner.Wave7TestRunner", return_value=runner)
            )
            for name in ("identity", "empty_application", "vacant_test_name", "verify_dropped"):
                stack.enter_context(patch.object(db, name))
            stack.enter_context(
                patch.object(db, "read_only_connections", return_value=nullcontext())
            )
            stack.enter_context(
                patch.object(
                    db,
                    "fingerprint",
                    side_effect=["base", "seeded", "changed" if changed else "seeded", "base"],
                )
            )
            stack.enter_context(patch("apps.intake_workflow.fixtures.seed_reference_catalog"))
            stack.enter_context(
                patch(
                    "tools.fast8_browser_conformance.run.catalog_preflight",
                    return_value={"result": "READY"},
                )
            )
            browser = stack.enter_context(
                patch(
                    "tools.fast9_pg_browser_catalog.run.browsers",
                    return_value={"browser": "PASS", "catalog": "PASS"},
                )
            )
            if browser_error:
                browser.side_effect = RuntimeError("deliberate failure")
            report = {}
            postgres(report)
        runner.teardown_databases.assert_called_once_with(["created-by-trusted-runner"])
        runner.teardown_test_environment.assert_called_once()
        return report

    def test_browser_exception_still_tears_down(self):
        report = self.fault_scenario(browser_error=True)
        self.assertEqual(report["catalog"], "FAIL")
        self.assertEqual(report["teardown"], "PASS")
        self.assertEqual(aggregate(report), "FAIL")

    def test_mutated_database_overrides_browser_pass(self):
        report = self.fault_scenario(changed=True)
        self.assertEqual(report["database_unchanged"], "FAIL")
        self.assertEqual(report["teardown"], "PASS")
        self.assertEqual(aggregate(report), "FAIL")

    def test_teardown_failure_overrides_browser_pass(self):
        report = self.fault_scenario(cleanup_error=True)
        self.assertEqual(report["teardown"], "FAIL")
        self.assertEqual(aggregate(report), "FAIL")

    def test_readonly_receiver_checks_actual_identity_and_setting(self):
        with (
            patch("django.db.backends.signals.connection_created.connect") as connect,
            patch("django.db.backends.signals.connection_created.disconnect") as disconnect,
            patch("django.db.connections.close_all"),
        ):
            with db.read_only_connections():
                protect = connect.call_args.args[0]
                connection = Mock(alias="default", settings_dict={"NAME": "wrong"})
                with self.assertRaisesRegex(AssertionError, "IDENTITY"):
                    protect(None, connection)
                connection.cursor.assert_not_called()
                connection.settings_dict["NAME"] = db.TEST
                cursor = Mock()
                connection.cursor.return_value = nullcontext(cursor)
                cursor.fetchone.return_value = ("wrong", "wave7_synthetic")
                with self.assertRaisesRegex(AssertionError, "IDENTITY"):
                    protect(None, connection)
                cursor.reset_mock()
                cursor.fetchone.side_effect = [(db.TEST, "wave7_synthetic"), ("off",)]
                with self.assertRaisesRegex(AssertionError, "READ_ONLY"):
                    protect(None, connection)
                cursor.fetchone.side_effect = [(db.TEST, "wave7_synthetic"), ("on",)]
                protect(None, connection)
            disconnect.assert_called_once_with(protect)


if __name__ == "__main__":
    unittest.main()
