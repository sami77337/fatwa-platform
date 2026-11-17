"""P0 negative boundaries with independent synthetic setup and real PostgreSQL."""

import io
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection, connections, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework_web.models import ThrottleBucket
from apps.platform_recovery import maintenance
from apps.platform_recovery.integration import MaintenanceUnavailable, mutation_scope
from apps.private_media.filesystem import FileSystemStorage
from tests.casework.test_http import WEB_SETTINGS


@override_settings(FATWA_RECOVERY_MAINTENANCE_REQUIRED=False)
class MaintenanceP0Tests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v12-independent-maintenance-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = FileSystemStorage(self.root / "private", synthetic_fixtures_only=True)
        self.control = self.root / "control"
        self.control.mkdir(mode=0o700)
        maintenance.initialize(
            root=self.control, storage=self.storage, synthetic_fixtures_only=True
        )
        self.overlay = override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=str(self.control),
            FATWA_PRIVATE_MEDIA_STORAGE=self.storage,
        )
        self.overlay.enable()
        self.addCleanup(self.overlay.disable)

    def freeze(self):
        self.assertEqual(
            maintenance.enter(root=self.control, synthetic_fixtures_only=True)["phase"], "FROZEN"
        )

    def test_get_and_head_throttle_cannot_write_or_disclose_control_when_frozen(self):
        options = {
            **WEB_SETTINGS,
            "MIDDLEWARE": [
                "apps.platform_recovery.middleware.MaintenanceGuard",
                *WEB_SETTINGS["MIDDLEWARE"],
            ],
        }
        with override_settings(**options):
            client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
            self.assertEqual(client.get("/casework/").status_code, 200)
            before = list(ThrottleBucket.objects.order_by("pk").values())
            self.assertTrue(before, "Positive control: this GET really writes a throttle row")
            self.freeze()
            for method in (client.get, client.head):
                response = method("/casework/")
                self.assertEqual(response.status_code, 503)
                self.assertIn("no-store", response["Cache-Control"])
                for secret in (
                    str(self.root),
                    connection.settings_dict["NAME"],
                    "generation",
                    "private_root",
                ):
                    self.assertNotIn(secret, response.content.decode())
            self.assertEqual(list(ThrottleBucket.objects.order_by("pk").values()), before)

    def test_failing_on_commit_callback_holds_lease_until_exception_then_releases(self):
        entered, release = threading.Event(), threading.Event()
        observed = []

        def writer():
            try:
                with mutation_scope(), transaction.atomic():
                    ThrottleBucket.objects.create(key="v12-callback", window=1, requests=1)

                    def callback():
                        entered.set()
                        if not release.wait(10):
                            raise AssertionError("test synchronization timeout")
                        # Committed work still holds admission while callback executes.
                        with mutation_scope():
                            ThrottleBucket.objects.filter(pk="v12-callback").update(requests=2)
                        raise ValueError("synthetic callback failure")

                    transaction.on_commit(callback)
            except Exception as exc:
                observed.append((type(exc), str(exc)))
            finally:
                connections.close_all()

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            self.assertTrue(entered.wait(10))
            self.assertEqual(ThrottleBucket.objects.get(pk="v12-callback").requests, 1)
            self.assertEqual(
                maintenance.enter(root=self.control, synthetic_fixtures_only=True)["phase"],
                "DRAINING",
            )
            with self.assertRaises(MaintenanceUnavailable), mutation_scope():
                self.fail("new write admitted while draining")
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(observed, [(ValueError, "synthetic callback failure")])
        self.assertEqual(ThrottleBucket.objects.get(pk="v12-callback").requests, 2)
        self.freeze()

    def test_outer_atomic_cannot_schedule_callback_beyond_admission(self):
        called = []
        with transaction.atomic():
            with self.assertRaises(MaintenanceUnavailable), mutation_scope():
                transaction.on_commit(lambda: called.append(True))
        self.assertEqual(called, [])
        self.freeze()

    def test_flush_rejected_before_executing_destructive_sql(self):
        self.freeze()
        reached = []

        class UnsafeBoundary(RuntimeError):
            pass

        def trap(*args, **kwargs):
            reached.append("execute_sql_flush")
            raise UnsafeBoundary("probe stops before any truncate")

        with patch.object(connection.ops, "execute_sql_flush", side_effect=trap):
            try:
                call_command(
                    "flush",
                    interactive=False,
                    verbosity=0,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            except Exception:
                pass
        self.assertEqual(
            reached, [], "P0: stock flush reached destructive SQL execution boundary while FROZEN"
        )

    def test_loaddata_cannot_insert_fixture_row_while_frozen(self):
        fixture = self.root / "probe.json"
        fixture.write_text(
            json.dumps(
                [
                    {
                        "model": "casework_web.throttlebucket",
                        "pk": "v12-loader",
                        "fields": {"window": 1, "requests": 1},
                    }
                ]
            )
        )
        self.freeze()
        try:
            call_command(
                "loaddata", str(fixture), verbosity=0, stdout=io.StringIO(), stderr=io.StringIO()
            )
        except Exception:
            pass
        self.assertFalse(
            ThrottleBucket.objects.filter(pk="v12-loader").exists(),
            "P0: loaddata committed a row while FROZEN",
        )

    def test_shell_command_cannot_execute_writer_while_frozen(self):
        self.freeze()
        marker = self.root / "shell-writer-ran"
        try:
            call_command(
                "shell",
                command=f"from pathlib import Path; Path({str(marker)!r}).write_text('synthetic')",
                verbosity=0,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        except Exception:
            pass
        self.assertFalse(marker.exists(), "P0: administrative shell executed while FROZEN")
