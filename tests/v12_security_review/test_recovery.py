"""Independent downgrade probe: never invoke production or create real-content backups."""

import os
import tempfile
from pathlib import Path

from django.test import TransactionTestCase, override_settings

from apps.platform_recovery import maintenance, service
from apps.private_media.filesystem import FileSystemStorage


@override_settings(FATWA_RECOVERY_MAINTENANCE_REQUIRED=False)
class RecoveryP0Tests(TransactionTestCase):
    def test_public_legacy_snapshot_cannot_write_plaintext_in_closed_campaign(self):
        pg_bin = os.environ.get("V12_PG_BIN")
        self.assertTrue(
            pg_bin, "Set V12_PG_BIN to the binary directory of the tested PostgreSQL major"
        )
        with tempfile.TemporaryDirectory(prefix="v12-independent-downgrade-") as temp:
            root = Path(temp)
            storage = FileSystemStorage(root / "private", synthetic_fixtures_only=True)
            control = root / "control"
            control.mkdir(mode=0o700)
            maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
            maintenance.enter(root=control, synthetic_fixtures_only=True)
            with override_settings(
                FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
                FATWA_RECOVERY_MAINTENANCE_ROOT=str(control),
                FATWA_PRIVATE_MEDIA_STORAGE=storage,
            ):
                # No compatibility/legacy opt-in supplied. Synthetic and offline
                # acknowledgements do not authorize encryption downgrade.
                try:
                    service.snapshot(
                        scratch=root,
                        storage=storage,
                        pg_bin=pg_bin,
                        synthetic_fixtures_only=True,
                        offline=True,
                    )
                except (service.RecoveryError, RuntimeError):
                    pass
                found = [
                    p.name
                    for p in root.rglob("*")
                    if p.is_file() and p.name in {"database.dump", "schema.sql", "manifest.json"}
                ]
                self.assertEqual(
                    found, [], "P0: direct legacy API published plaintext backup artifacts"
                )

    def test_encrypted_snapshot_positive_control_publishes_ciphertext_only(self):
        from apps.platform_recovery import encrypted

        pg_bin = os.environ.get("V12_PG_BIN")
        self.assertTrue(pg_bin)
        with (
            tempfile.TemporaryDirectory(prefix="v12-independent-sealed-") as temp,
            tempfile.TemporaryDirectory(prefix="v12-independent-key-") as key_temp,
        ):
            root = Path(temp)
            storage = FileSystemStorage(root / "private", synthetic_fixtures_only=True)
            control = root / "control"
            control.mkdir(mode=0o700)
            maintenance.initialize(root=control, storage=storage, synthetic_fixtures_only=True)
            maintenance.enter(root=control, synthetic_fixtures_only=True)
            key = Path(key_temp) / "ephemeral.key"
            encrypted.generate_key(path=key, synthetic_fixtures_only=True)
            with override_settings(
                FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
                FATWA_RECOVERY_MAINTENANCE_ROOT=str(control),
                FATWA_PRIVATE_MEDIA_STORAGE=storage,
            ):
                sealed = encrypted.snapshot(
                    scratch=root,
                    storage=storage,
                    pg_bin=pg_bin,
                    key_file=key,
                    maintenance_root=control,
                    synthetic_fixtures_only=True,
                )
                verified = encrypted.verify(
                    bundle=sealed["bundle"],
                    expected_ciphertext_sha256=sealed["ciphertext_sha256"],
                    key_file=key,
                )
            self.assertEqual(verified["state"], "VERIFIED")
            bundle = Path(sealed["bundle"])
            self.assertEqual({p.name for p in bundle.iterdir()}, {"backup.fernet", "COMPLETE"})
            self.assertNotIn(key.read_bytes(), (bundle / "backup.fernet").read_bytes())
            self.assertEqual(list(root.rglob("database.dump")), [])
            self.assertEqual(maintenance.status(root=control)["phase"], "FROZEN")
