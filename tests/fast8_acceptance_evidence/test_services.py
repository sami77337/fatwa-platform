"""Negative evidence checks use only fixed or explicitly fabricated synthetic bytes."""

import copy
import io
import os
from hashlib import sha256
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_export.services import encode_json
from apps.fast8_acceptance_evidence import services
from apps.fast8_acceptance_evidence.services import build_report, verify_report


class EvidenceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(synthetic_fixtures_only=True)
        cls.data = cls.report.payload()
        cls.upstream = cls.data["artifacts"][0]["payload"]

    def altered(self, data):
        with patch.object(services, "_collect", return_value=encode_json(data)):
            return build_report(synthetic_fixtures_only=True).payload()

    def assert_closed(self, result, status="FAIL"):
        self.assertEqual(result["producer"]["status"], status)
        self.assertEqual(result["artifacts"], [])
        self.assertNotIn("PASS", [row["status"] for row in result["matrix"]])
        self.assertFalse(result["authorization"]["allowed"])
        self.assertEqual(set(result["acceptance"].values()), {"BLOCKED"})

    def test_real_services_produce_deterministic_blocked_matrix(self):
        self.assertEqual(
            self.report.json_bytes, build_report(synthetic_fixtures_only=True).json_bytes
        )
        self.assertEqual(self.data["status"], "BLOCKED")
        self.assertEqual(self.data["producer"]["status"], "PASS")
        self.assertEqual(self.data["execution_commit"], {"status": "NOT_SUPPLIED", "sha": None})
        self.assertEqual(sum(self.data["counts"].values()), len(self.data["matrix"]))
        self.assertLess(len(self.report.json_bytes), services.MAX_REPORT_BYTES)
        self.assertIn("U03/U10 OWNER_APPROVAL_PENDING", self.data["holds"])

    def test_raw_upstream_provenance_and_every_pointer_resolve(self):
        artifact = self.data["artifacts"][0]
        original = services._collect()
        self.assertEqual(encode_json(artifact["payload"]), original)
        self.assertEqual(artifact["sha256"], sha256(original).hexdigest())
        self.assertEqual(artifact["bytes"], len(original))
        for row in self.data["matrix"]:
            if row["evidence"] is None:
                continue
            self.assertEqual(row["evidence"]["artifact_id"], artifact["id"])
            value = artifact["payload"]
            for part in row["evidence"]["json_pointer"].split("/")[1:]:
                value = value[int(part)] if isinstance(value, list) else value[part]

    def test_owner_artifacts_remain_missing_with_expected_counts(self):
        rows = {row["id"]: row for row in self.data["matrix"]}
        for key, count in (
            ("historical_actions", 70),
            ("historical_transitions", 58),
            ("U03", 48),
            ("U10", 28),
        ):
            row = rows[f"owner.{key}"]
            self.assertEqual(row["status"], "NOT_SUPPLIED")
            self.assertEqual(row["expected_artifact"]["expected"], count)
            self.assertEqual(row["expected_artifact"]["supplied"], 0)
        for index, (name, digest) in enumerate(services.ARCHIVES, 1):
            row = rows[f"owner.archive.{index}"]
            self.assertEqual(row["status"], "NOT_SUPPLIED")
            self.assertEqual(row["expected_artifact"]["name"], name)
            self.assertEqual(row["expected_artifact"]["sha256"], digest)
            self.assertIsNone(row["expected_artifact"]["observed_sha256"])

    def test_synthetic_pass_cannot_promote_ci_browser_or_owner_acceptance(self):
        rows = {row["id"]: row for row in self.data["matrix"]}
        for identifier in (
            "ci.B6",
            "ci.C6",
            "ci.D6",
            "technical.http",
            "technical.browser",
            "technical.postgres",
        ):
            self.assertEqual(rows[identifier]["status"], "NOT_RUN")
        self.assertEqual(self.data["counts"]["PASS"], 3)
        self.assertEqual(set(self.data["acceptance"].values()), {"BLOCKED"})
        self.assertEqual(
            {row["id"] for row in rows.values() if row["status"] == "NOT_CONNECTED"},
            {"connection.transcript_to_stock_queue", "connection.permission_to_case"},
        )
        for row in rows.values():
            self.assertTrue(row["requirement_ar"])
            self.assertTrue(set(row["depends_on"]) <= rows.keys())

    def test_arabic_crlf_timestamps_and_original_identities_are_preserved(self):
        source = self.upstream
        csv = next(
            item
            for item in source["projections"]
            if item["identity"]["case_key"] == "batch-synthetic-csv-1"
        )
        self.assertEqual(
            csv["packet"]["intake"]["question"], "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  "
        )
        rebuilt = self.report.payload()["artifacts"][0]["payload"]
        self.assertEqual(rebuilt["transcript"], source["transcript"])
        self.assertEqual(rebuilt["projections"], source["projections"])
        self.assertIn("قبول".encode(), self.report.json_bytes)

    def test_production_and_non_boolean_opt_in_rejected_before_collection(self):
        with patch.object(services, "_collect") as collect:
            for flag in (False, None, 1, "true"):
                with self.subTest(flag=flag), self.assertRaises(ValueError):
                    build_report(synthetic_fixtures_only=flag)
            for env in (
                {"FATWA_PRODUCTION": "1"},
                {"DJANGO_SETTINGS_MODULE": "config.settings.production"},
            ):
                with patch.dict(os.environ, env), self.assertRaises(ValueError):
                    build_report(synthetic_fixtures_only=True)
            collect.assert_not_called()

    def test_missing_producer_fixture_and_failed_verification_are_distinct(self):
        for error, status in (
            (ImportError("private"), "NOT_CONNECTED"),
            (OSError("private"), "NOT_SUPPLIED"),
            (ValueError("private"), "FAIL"),
        ):
            with self.subTest(status=status), patch.object(services, "_collect", side_effect=error):
                result = build_report(synthetic_fixtures_only=True)
                self.assert_closed(result.payload(), status)
                self.assertNotIn(b"private", result.json_bytes)

    def test_bad_schema_scope_or_execution_cannot_emit_partial_success(self):
        for path, value in (
            (["schema"], "unrecognized"),
            (["result"], "PASS"),
            (["synthetic_only"], 1),
            (["holds"], []),
            (["execution", "services"], "FAIL"),
            (["execution", "browser"], "PASS"),
            (["execution", "writes"], True),
            (["execution", "network_requests"], True),
        ):
            data = copy.deepcopy(self.upstream)
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assert_closed(self.altered(data))

    def test_forged_policy_acceptance_grants_and_empty_probes_fail(self):
        changes = (
            (["allowed"], True),
            (["active_grants"], 1),
            (["active_grants"], False),
            (["runtime_executable"], True),
            (["evidence", "policy_approval_verified"], True),
            (["evidence", "source_acceptance_passed"], True),
            (["evidence", "coverage", "U03", "approved"], 48),
            (["evidence", "coverage", "historical_actions", "supplied"], 70),
            (["adversarial_checks", "checks"], []),
            (["adversarial_checks", "checks", 0, "passed"], 1),
            (["requests"], []),
        )
        for path, value in changes:
            data = copy.deepcopy(self.upstream)
            target = data["permission_gaps"]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assert_closed(self.altered(data))

    def test_owner_source_hashes_are_not_observations(self):
        for key, value in (
            ("status", "PASS"),
            ("observed_sha256", {"archive": "a" * 64}),
            ("owner_acceptance", "PASS"),
            ("database_verification", "PASS"),
        ):
            data = copy.deepcopy(self.upstream)
            data["source_readiness"][key] = value
            with self.subTest(key=key):
                self.assert_closed(self.altered(data))

    def test_workflow_and_projection_approval_tampering_fails(self):
        for key, value in (
            ("invariants_passed", False),
            ("invariants_passed", 1),
            ("owner_transitions", "PASS"),
            ("steps", []),
        ):
            data = copy.deepcopy(self.upstream)
            data["workflow_invariants"][key] = value
            self.assert_closed(self.altered(data))
        for key in ("persisted", "scholarly_approval"):
            data = copy.deepcopy(self.upstream)
            data["projections"][0][key] = True
            self.assert_closed(self.altered(data))

    def test_missing_duplicate_or_invented_connection_fails(self):
        changes = (
            self.upstream["connections"][:-1],
            self.upstream["connections"][:-1] + self.upstream["connections"][:1],
            [{**edge, "status": "CONNECTED"} for edge in self.upstream["connections"]],
        )
        for edges in changes:
            data = copy.deepcopy(self.upstream)
            data["connections"] = edges
            self.assert_closed(self.altered(data))

    def test_malformed_or_oversize_upstream_fails_without_parsing_large_input(self):
        for raw in (
            None,
            "{}",
            b"{}",
            b"{",
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b"x" * (services.MAX_REPORT_BYTES + 1),
        ):
            with self.subTest(kind=type(raw)), patch.object(services, "_collect", return_value=raw):
                self.assert_closed(build_report(synthetic_fixtures_only=True).payload())

    def test_replay_rejects_changed_hash_status_whitespace_or_unbounded_bytes(self):
        verify_report(self.report.json_bytes, synthetic_fixtures_only=True)
        altered = self.report.payload()
        altered["acceptance"]["owner"] = "PASS"
        for raw in (
            encode_json(altered),
            self.report.json_bytes + b" ",
            b"{}",
            None,
            "{}",
            b"x" * (services.MAX_REPORT_BYTES + 1),
        ):
            with self.subTest(kind=type(raw)), self.assertRaises(ValueError):
                verify_report(raw, synthetic_fixtures_only=True)
        with patch.object(services, "_collect") as collect, self.assertRaises(ValueError):
            verify_report(b"x" * (services.MAX_REPORT_BYTES + 1), synthetic_fixtures_only=True)
        collect.assert_not_called()

    def test_no_write_network_process_database_or_owner_archive_access(self):
        real_open = io.open

        def read_only(file, mode="r", *args, **kwargs):
            self.assertFalse(any(flag in mode for flag in "wax+"))
            self.assertFalse(str(file).lower().endswith(".zip"))
            return real_open(file, mode, *args, **kwargs)

        with (
            patch("io.open", side_effect=read_only),
            patch("builtins.open", side_effect=read_only),
            patch("socket.socket", side_effect=AssertionError("network")),
            patch("subprocess.Popen", side_effect=AssertionError("process")),
            patch(
                "apps.reference_links.django_adapter.DjangoCatalog.lookup",
                side_effect=AssertionError("database"),
            ),
        ):
            self.assertEqual(
                build_report(synthetic_fixtures_only=True).json_bytes, self.report.json_bytes
            )
