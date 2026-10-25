"""Real fixed-fixture exports: exact provenance, bounds and replay."""

import csv
import io
import json
import os
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.editorial_workbench.packets import build_packet
from apps.editorial_workbench.services import build_cases, build_prepared_workbench


class ExportTests(SimpleTestCase):
    def build(self):
        from apps.editorial_export.services import build_export

        return build_export(synthetic_fixtures_only=True)

    def test_complete_deterministic_export_matches_existing_packets_and_sources(self):
        bundle = self.build()
        self.assertEqual(bundle.files, self.build().files)
        report = bundle.report()
        self.assertTrue(report["synthetic_only"])
        self.assertEqual(len(report["cases"]), 20)
        self.assertEqual(len(report["batches"]), 4)
        self.assertEqual(
            [b["batch_id"] for b in report["batches"]],
            sorted(b["batch_id"] for b in report["batches"]),
        )
        prepared = build_prepared_workbench()
        cases = {c.key: c for c in (*build_cases(), *prepared.cases)}
        batches = {b.batch_id: b for b in prepared.batches}
        keys = []
        for entry in report["cases"]:
            key = entry["packet"]["identity"]["case_key"]
            keys.append(key)
            case = cases[key]
            packet = build_packet(case, batches.get(getattr(case, "batch_id", None)))
            self.assertEqual(entry["packet"], packet.payload())
            self.assertEqual(entry["packet_sha256"], packet.sha256)
            self.assertEqual(entry["navigation"]["case_key"], key)
            self.assertIn(key, entry["navigation"]["packet_path"])
            self.assertIsNone(entry["packet"]["scholarly_decision"])
        self.assertEqual(keys, sorted(keys))
        malformed = next(b for b in report["batches"] if b["batch_id"] == "synthetic-malformed")
        self.assertEqual(malformed["record_count"], 0)
        self.assertEqual(malformed["error_code"], "MALFORMED_INPUT")
        for batch in report["batches"]:
            self.assertEqual(
                sha256(batch["raw_source"].encode()).hexdigest(), batch["input_sha256"]
            )
        report["cases"].clear()
        self.assertEqual(len(bundle.report()["cases"]), 20)

    def test_csv_cells_roundtrip_all_values_without_normalization_or_formula_execution(self):
        from apps.editorial_export.services import encode_csv

        samples = [
            "=1+1",
            "+1",
            "-2",
            "@SUM(A1)",
            "\t=1",
            "  سُؤَالٌ\r\n e\u0301  ",
            None,
            {"a": [1, True]},
        ]
        data = encode_csv(("value",), [{"value": value} for value in samples])
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))
        self.assertEqual([json.loads(row["value"]) for row in rows], samples)
        self.assertTrue(
            all(not row["value"].startswith(("=", "+", "-", "@", "\t", "\r")) for row in rows)
        )
        bundle = self.build()
        csv_cases = list(csv.DictReader(io.StringIO(bundle.file("cases.csv").decode(), newline="")))
        self.assertEqual(len(csv_cases), 20)
        for row, entry in zip(csv_cases, bundle.report()["cases"], strict=True):
            self.assertEqual({k: json.loads(v) for k, v in row.items()}, entry)
        csv_batches = list(
            csv.DictReader(io.StringIO(bundle.file("batches.csv").decode(), newline=""))
        )
        self.assertEqual(
            [{k: json.loads(v) for k, v in row.items()} for row in csv_batches],
            bundle.report()["batches"],
        )

    def test_manifest_digests_and_replay_reject_even_coordinated_tampering(self):
        from apps.editorial_export.services import ExportError, verify_export

        bundle = self.build()
        files = dict(bundle.files)
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(set(manifest["files"]), {"report.json", "cases.csv", "batches.csv"})
        for name, metadata in manifest["files"].items():
            self.assertEqual(
                metadata, {"bytes": len(files[name]), "sha256": sha256(files[name]).hexdigest()}
            )
        verify_export(files, synthetic_fixtures_only=True)
        changed = dict(files)
        changed["cases.csv"] += b"\n"
        manifest["files"]["cases.csv"] = {
            "bytes": len(changed["cases.csv"]),
            "sha256": sha256(changed["cases.csv"]).hexdigest(),
        }
        changed["manifest.json"] = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        with self.assertRaises(ExportError):
            verify_export(changed, synthetic_fixtures_only=True)
        for bad in ({}, {**files, "extra.txt": b""}, {**files, "report.json": b"\xff"}):
            with self.subTest(bad=list(bad)), self.assertRaises(ExportError):
                verify_export(bad, synthetic_fixtures_only=True)

    def test_explicit_opt_in_and_production_guards_precede_fixture_loading(self):
        from apps.editorial_export import services

        with patch.object(services, "build_cases") as loader:
            for flag in (False, None, 1, "true"):
                with self.assertRaises(services.ExportError):
                    services.build_export(synthetic_fixtures_only=flag)
            for flag in ("1", "true", ""):
                with (
                    patch.dict(os.environ, {"FATWA_PRODUCTION": flag}),
                    self.assertRaises(services.ExportError),
                ):
                    self.build()
            with override_settings(FATWA_PRODUCTION=True), self.assertRaises(services.ExportError):
                self.build()
            with (
                override_settings(SETTINGS_MODULE="config.settings.production"),
                self.assertRaises(services.ExportError),
            ):
                self.build()
            loader.assert_not_called()

    def test_bounds_invalid_unicode_and_duplicate_identities_fail_closed(self):
        from apps.editorial_export import services

        for name, bound in (
            ("MAX_CASES", 1),
            ("MAX_BATCHES", 1),
            ("MAX_FILE_BYTES", 50),
            ("MAX_BUNDLE_BYTES", 50),
        ):
            with (
                self.subTest(name=name),
                patch.object(services, name, bound),
                self.assertRaises(services.ExportError),
            ):
                self.build()
        cases = build_cases()
        bad = replace(cases[0], question="\ud800", record=None)
        for supplied in ((bad, *cases[1:]), (*cases, cases[0])):
            with (
                patch.object(services, "build_cases", return_value=supplied),
                self.assertRaises(services.ExportError),
            ):
                self.build()
        prepared = build_prepared_workbench()
        bad_batch = replace(prepared.batches[0], raw_source="altered")
        with (
            patch.object(
                services,
                "build_prepared_workbench",
                return_value=replace(prepared, batches=(bad_batch, *prepared.batches[1:])),
            ),
            self.assertRaises(services.ExportError),
        ):
            self.build()

    def test_serializer_rejects_unbounded_and_unsupported_values(self):
        from apps.editorial_export.services import ExportError, encode_json

        cycle = []
        cycle.append(cycle)
        for value in (
            {"x": float("nan")},
            {1: "bad"},
            {"x": "\ud800"},
            {"x": 2**64},
            {"x": cycle},
            {"x": object()},
        ):
            with self.subTest(value=type(value)), self.assertRaises(ExportError):
                encode_json(value)

    def test_csv_and_json_apply_byte_and_text_limits_even_to_empty_output(self):
        from apps.editorial_export import services

        with patch.object(services, "MAX_FILE_BYTES", 4):
            with self.assertRaises(services.ExportError):
                services.encode_csv(("long_header",), [])
        with patch.object(services, "MAX_STRING_CHARS", 2):
            with self.assertRaises(services.ExportError):
                services.encode_json({"x": "abc"})
        with patch.object(services, "MAX_NODES", 2):
            with self.assertRaises(services.ExportError):
                services.encode_json({"x": [1, 2]})
        with self.assertRaises(services.ExportError):
            services.encode_csv(("value",), [{"different": 1}])
