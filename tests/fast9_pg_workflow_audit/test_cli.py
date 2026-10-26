"""CLI opt-in and redaction boundaries; no database connection."""

import io
import json
import os
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.fast9_pg_workflow_audit import adapter
from apps.intake_workflow import guards
from tests.fast9_pg_workflow_audit.test_adapter import sample
from tools.fast9_pg_workflow_audit import __main__ as cli


class CliTests(SimpleTestCase):
    def arguments(self):
        from dataclasses import asdict

        _, identity = sample()
        args = ["--synthetic-only"]
        for name, value in asdict(identity).items():
            args += ["--" + name.replace("_", "-"), str(value)]
        return args

    def test_no_profile_is_not_run_without_setup(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings.test"}),
            patch("django.setup") as setup,
            redirect_stdout(output),
        ):
            status = cli.main(self.arguments())
        self.assertEqual(status, 3)
        self.assertEqual(json.loads(output.getvalue())["status"], "NOT_RUN")
        setup.assert_not_called()

    def test_missing_ack_and_abbreviations_rejected(self):
        for args in ([], self.arguments()[1:], ["--synthetic-on", *self.arguments()[1:]]):
            with (
                self.subTest(args=args),
                patch("sys.stderr", io.StringIO()),
                self.assertRaises(SystemExit) as caught,
            ):
                cli.main(args)
            self.assertEqual(caught.exception.code, 2)

    def test_setup_error_is_redacted(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings.wave7_test"}),
            patch("django.setup", side_effect=RuntimeError("secret-user/password")),
            redirect_stdout(output),
        ):
            status = cli.main(self.arguments())
        self.assertEqual(status, 3)
        self.assertEqual(
            json.loads(output.getvalue()), {"status": "NOT_RUN", "reason": "READ_UNAVAILABLE"}
        )

    def test_supplied_test_name_and_readonly_options_reach_adapter_without_base_connection(self):
        _, identity = sample()
        connection = SimpleNamespace(
            connection=None, settings_dict={"NAME": "wave7_synthetic_fast9"}
        )
        target = guards.DatabaseTarget(
            "default", "wave7_synthetic_fast9", "wave7_synthetic_fast9", identity.database_name
        )
        output = io.StringIO()

        def read(value, **kwargs):
            self.assertEqual(value, identity)
            self.assertEqual(kwargs, {"synthetic_fixtures_only": True})
            self.assertEqual(connection.settings_dict["NAME"], identity.database_name)
            self.assertIn(
                "default_transaction_read_only=on", connection.settings_dict["OPTIONS"]["options"]
            )
            return adapter.AuditRead(
                "CONNECTED", "BOUNDED_SYNTHETIC_READ", audit_sha256=identity.audit_sha256
            )

        with (
            patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings.wave7_test"}),
            patch("django.setup"),
            override_settings(WAVE7_TEST_DATABASE_NAME=identity.database_name),
            patch("django.db.connections", {"default": connection}),
            patch.object(guards, "validate_write_configuration", return_value=target),
            patch.object(adapter, "read_stored_audit", side_effect=read),
            redirect_stdout(output),
        ):
            status = cli.main(self.arguments())
        self.assertEqual(status, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "CONNECTED")
        self.assertIsNone(report["provenance"])
        self.assertEqual(report["revision_connection"], "NOT_CONNECTED")
