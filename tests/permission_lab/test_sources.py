"""The lab consumes pinned synthetic contracts, never historical grants."""

import importlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class PermissionSourceTests(unittest.TestCase):
    def sources(self):
        try:
            return importlib.import_module("apps.permission_lab.sources")
        except ModuleNotFoundError:
            self.fail("The pinned permission source loader is not implemented")

    def test_loads_only_small_inert_synthetic_inventory(self):
        source = self.sources()
        inventory = source.load_inventory()
        self.assertEqual(inventory["fixture_kind"], "SYNTHETIC")
        self.assertEqual(len(inventory["actions"]), 4)
        self.assertEqual(len(inventory["transitions"]), 1)
        self.assertEqual(source.HISTORICAL_COUNTS, {"actions": 70, "transitions": 58})
        self.assertEqual(source.SOURCE_COMMIT, "88c411852d1a90e62ec71ab1c9ae2278f72d0c76")
        self.assertEqual(inventory["policy"]["owner_approval"], "OWNER_APPROVAL_PENDING")
        self.assertTrue(
            all(
                row["deny_default"] == "DENY_DEFAULT"
                and row["callable"] is False
                and row["grant_effect"] == "NONE"
                for row in inventory["actions"]
            )
        )

    def test_each_load_returns_fresh_inventory(self):
        source = self.sources()
        first = source.load_inventory()
        first["actions"][0]["grant_effect"] = "ALLOW"
        self.assertEqual(source.load_inventory()["actions"][0]["grant_effect"], "NONE")

    def test_no_caller_paths_or_inventory_are_accepted(self):
        source = self.sources()
        with self.assertRaises(TypeError):
            source.load_inventory(Path("caller.json"))
        with self.assertRaises(TypeError):
            source.load_inventory(inventory={})

    def test_missing_or_tampered_bundled_files_fail_closed(self):
        source = self.sources()
        original = Path(source.__file__).parent / "upstream"
        names = (
            "validator.py",
            "inventory.schema.json",
            "synthetic_inventory.json",
            "synthetic_review_excerpt.json",
        )
        for name in names:
            for mode in ("missing", "tampered"):
                with self.subTest(name=name, mode=mode), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder) / "upstream"
                    shutil.copytree(original, root)
                    file = root / name
                    if mode == "missing":
                        file.unlink()
                    else:
                        file.write_bytes(file.read_bytes() + b" ")
                    with patch.object(source, "_UPSTREAM_ROOT", root):
                        with self.assertRaisesRegex(
                            source.SourceUnavailable, "SOURCE_CONTRACT_UNAVAILABLE"
                        ):
                            source.load_inventory()

    def test_upstream_policy_rejection_fails_closed(self):
        source = self.sources()
        upstream = importlib.import_module("apps.permission_lab.upstream.validator")
        with patch.object(upstream, "inspect_structure", return_value=[{"code": "SHADOW_GRANT"}]):
            with self.assertRaises(source.SourceUnavailable):
                source.load_inventory()

    def test_original_validator_rejects_pending_policy_activation_and_shadow_grants(self):
        source = self.sources()
        upstream = importlib.import_module("apps.permission_lab.upstream.validator")
        for category, key, value in (
            ("policy", "owner_approval", "APPROVED"),
            ("policy", "scholarly_authorities", ["MUFTI", "ORGANIZER_ADMIN"]),
            ("action", "grant_effect", "ALLOW"),
            ("action", "allow", True),
            ("action", "candidate_principals", [{"kind": "ROLE", "name": "*"}]),
            ("action", "callable", True),
            ("transition", "enabled", True),
        ):
            with self.subTest(category=category, key=key):
                inventory = source.load_inventory()
                target = (
                    inventory["policy"]
                    if category == "policy"
                    else (
                        inventory["actions"][2]
                        if category == "action"
                        else inventory["transitions"][0]
                    )
                )
                target[key] = value
                self.assertTrue(upstream.inspect_structure(inventory, synthetic=True))

    def test_manifest_pins_match_bundled_bytes(self):
        import hashlib

        source = self.sources()
        root = Path(source.__file__).parent / "upstream"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_commit"], source.SOURCE_COMMIT)
        for item in manifest["files"]:
            self.assertEqual(
                hashlib.sha256((root / item["vendored_path"]).read_bytes()).hexdigest(),
                item["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
