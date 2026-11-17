"""P0 administration entrypoints use the same owned synthetic PostgreSQL database."""

import importlib
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.db.models.signals import post_migrate
from django.test import Client, TransactionTestCase, override_settings

from apps.casework_web.models import ThrottleBucket
from apps.platform_recovery import maintenance
from apps.platform_recovery.integration import require_admission
from apps.private_media.filesystem import FileSystemStorage
from apps.source_case_intake import services, simulators
from apps.source_case_intake.models import SourceReceipt
from tests.casework.test_http import WEB_SETTINGS


@override_settings(
    FATWA_RECOVERY_MAINTENANCE_REQUIRED=False,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
)
class StrictAdministrationTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v12-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = FileSystemStorage(self.root / "private", synthetic_fixtures_only=True)
        self.control = self.root / "control"
        self.control.mkdir(mode=0o700)
        maintenance.initialize(
            root=self.control, storage=self.storage, synthetic_fixtures_only=True
        )
        self.strict = override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=str(self.control),
            FATWA_PRIVATE_MEDIA_STORAGE=self.storage,
        )

    def freeze(self):
        state = maintenance.enter(root=self.control, synthetic_fixtures_only=True)
        self.assertEqual(state["phase"], "FROZEN")
        return state

    def test_generic_admin_rejected_before_execution_with_data_preserved(self):
        receipt = services.capture(
            raw=simulators.telegram(), context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )
        fixture = self.root / "never-load.json"
        fixture.write_text("[]")
        output = self.root / "never-export.json"
        actions = (
            ("flush", [], {"interactive": False}),
            ("loaddata", [str(fixture)], {}),
            ("dumpdata", [], {"output": str(output)}),
            ("shell", [], {"command": "raise AssertionError('shell executed')"}),
            ("dbshell", [], {}),
            ("clearsessions", [], {}),
            ("createcachetable", [], {}),
            ("test", [], {}),
        )
        with self.strict:
            for name, args, options in actions:
                with self.subTest(command=name):
                    self.assertEqual(get_commands()[name], "apps.intake_workflow")
                    with self.assertRaisesMessage(CommandError, "STRICT_ADMINISTRATION_UNSUPPORTED"):
                        call_command(name, *args, stdout=StringIO(), stderr=StringIO(), **options)
                    self.assertEqual(list(SourceReceipt.objects.values_list("pk", flat=True)), [receipt.pk])
                    self.assertFalse(output.exists())

    def test_missing_control_is_not_an_administration_escape(self):
        with override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=None,
        ):
            with self.assertRaisesMessage(CommandError, "STRICT_ADMINISTRATION_UNSUPPORTED"):
                call_command("shell", command="raise AssertionError('executed')")
            with self.assertRaisesMessage(CommandError, "MAINTENANCE_ADMINISTRATION_UNAVAILABLE"):
                call_command("migrate", verbosity=0)

    def test_explicit_legacy_mode_delegates_original_commands(self):
        # Never flush or launch a shell here. Verify compatibility at the original
        # execute boundary, which strict mode must not reach.
        for name in ("flush", "loaddata", "dumpdata", "dbshell", "shell", "clearsessions", "createcachetable", "test"):
            module = importlib.import_module(f"apps.intake_workflow.management.commands.{name}")
            with self.subTest(command=name), patch.object(
                module.DjangoCommand, "execute", return_value="legacy-delegate"
            ) as original:
                self.assertEqual(module.Command().execute(), "legacy-delegate")
                original.assert_called_once_with()

    def test_frozen_migration_rejected_before_native_command(self):
        self.freeze()
        with self.strict, patch(
            "apps.intake_workflow.management.commands.migrate.DjangoMigrate.execute"
        ) as native:
            with self.assertRaisesMessage(CommandError, "MAINTENANCE_ADMINISTRATION_UNAVAILABLE"):
                call_command("migrate", verbosity=0)
            native.assert_not_called()

    def test_native_migration_signals_hold_admission_until_complete(self):
        observed = []

        def receiver(sender, **kwargs):
            require_admission()
            state = maintenance.enter(root=self.control, synthetic_fixtures_only=True)
            observed.append(state["phase"])

        post_migrate.connect(receiver, weak=False, dispatch_uid="v12-admission-migration")
        try:
            with self.strict:
                call_command("migrate", verbosity=0, interactive=False, stdout=StringIO())
        finally:
            post_migrate.disconnect(dispatch_uid="v12-admission-migration")
        self.assertTrue(observed)
        self.assertEqual(set(observed), {"DRAINING"})
        self.freeze()

    def test_get_budget_rejects_missing_outer_middleware_without_writing(self):
        with self.strict, override_settings(**WEB_SETTINGS):
            response = Client().get("/casework/", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(ThrottleBucket.objects.count(), 0)
        self.assertEqual(len(response.cookies), 0)

    def test_full_get_boundary_preserves_budget_and_cookies_when_frozen(self):
        web = {
            **WEB_SETTINGS,
            "MIDDLEWARE": [
                "apps.platform_recovery.middleware.MaintenanceGuard",
                *WEB_SETTINGS["MIDDLEWARE"],
            ],
        }
        with self.strict, override_settings(**web):
            client = Client()
            self.assertEqual(client.get("/casework/", HTTP_HOST="127.0.0.1").status_code, 200)
            before = list(ThrottleBucket.objects.values())
            self.assertEqual(len(before), 1)
            self.freeze()
            response = client.get("/casework/", HTTP_HOST="127.0.0.1")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(list(ThrottleBucket.objects.values()), before)
            self.assertEqual(len(response.cookies), 0)
            self.assertIn("no-store", response["Cache-Control"])
