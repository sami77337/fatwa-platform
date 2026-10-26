"""Exercise real canonical producers; never read owner archives or a database."""

import copy
import json
import os
from hashlib import sha256
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_export.services import build_export, encode_json, verify_export
from apps.editorial_workbench.packets import MAX_PACKET_BYTES, serialize_packet


class PacketVerifierTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = build_export(synthetic_fixtures_only=True)
        cls.packets = {
            e["packet"]["identity"]["case_key"]: e["packet"] for e in cls.bundle.report()["cases"]
        }

    def setUp(self):
        self.packet = copy.deepcopy(self.packets["history"])
        self.manifest = json.loads(self.bundle.file("manifest.json"))

    def verify(self, packet=None, manifest=None, key="history"):
        from apps.fast8_packet_verifier.services import verify_packet

        return verify_packet(
            serialize_packet(self.packet if packet is None else packet),
            encode_json(self.manifest if manifest is None else manifest),
            case_key=key,
            synthetic_fixtures_only=True,
        )

    def rejected(self, code, **kwargs):
        from apps.fast8_packet_verifier.services import PacketVerificationError

        with self.assertRaises(PacketVerificationError) as caught:
            self.verify(**kwargs)
        self.assertEqual(caught.exception.code, "packet_verify: " + code)
        self.assertEqual(str(caught.exception), caught.exception.code)

    def test_every_fixed_case_has_exact_source_manifest_and_revision_receipt(self):
        for key, packet in self.packets.items():
            with self.subTest(key=key):
                raw = serialize_packet(packet)
                receipt = self.verify(packet=packet, key=key)
                self.assertEqual(receipt, self.verify(packet=packet, key=key))
                result = json.loads(receipt)
                self.assertEqual(result["status"], "VERIFIED")
                self.assertEqual(result["case_key"], key)
                self.assertEqual(result["packet_sha256"], sha256(raw).hexdigest())
                self.assertEqual(result["input_sha256"], packet["source"]["input_sha256"])
                self.assertEqual(
                    result["manifest_sha256"], sha256(encode_json(self.manifest)).hexdigest()
                )
                self.assertEqual(
                    result["revision_digests"],
                    [
                        {"number": r["number"], "sha256": sha256(serialize_packet(r)).hexdigest()}
                        for r in packet["snapshots"]
                    ],
                )
                self.assertEqual(
                    result["reference_ordinals"],
                    [r["reference_ordinal"] for r in packet["reference_verification"]["results"]],
                )
                self.assertNotIn("question", result)

    def test_case_key_is_required_exact_and_not_external_id_join(self):
        for key in (None, True, "", "unknown", self.packet["identity"]["external_id"]):
            with self.subTest(key=key):
                self.rejected("unknown_case", key=key)
        self.rejected("case_identity_mismatch", key="intake-1")
        a, b = "batch-synthetic-csv-2", "batch-synthetic-json-1"
        self.assertEqual(
            self.packets[a]["identity"]["external_id"], self.packets[b]["identity"]["external_id"]
        )
        self.rejected("case_identity_mismatch", packet=self.packets[a], key=b)

    def test_snapshot_missing_extra_reordered_and_cross_case(self):
        original = copy.deepcopy(self.packet["snapshots"])
        for records, code in (
            (original[:-1], "revision_missing"),
            (original + [original[0]], "revision_extra"),
            (original[::-1], "revision_order_mismatch"),
            ([original[0], original[0], *original[2:]], "revision_identity_mismatch"),
        ):
            self.packet["snapshots"] = records
            self.rejected(code)
        self.packet["snapshots"] = original
        self.packet["snapshots"][0] = self.packets["batch-synthetic-csv-1"]["snapshots"][0]
        self.rejected("revision_digest_mismatch")

    def test_revision_content_reference_order_and_metadata_are_immutable(self):
        for field, value in (("title", "tampered"), ("human_editor", "tampered"), ("number", True)):
            self.packet = copy.deepcopy(self.packets["history"])
            self.packet["snapshots"][0][field] = value
            self.rejected(
                "revision_identity_mismatch" if field == "number" else "revision_digest_mismatch"
            )
        self.packet = copy.deepcopy(self.packets["history"])
        snapshot = next(r for r in self.packet["snapshots"] if len(r["reference_links"]) > 1)
        snapshot["reference_links"].reverse()
        self.rejected("revision_digest_mismatch")

    def test_observations_cannot_be_removed_or_forged(self):
        self.packet["snapshot_observations"].pop()
        self.rejected("observation_missing")
        self.packet = copy.deepcopy(self.packets["history"])
        self.packet["snapshot_observations"][0]["changed_fields"] = ["answer"]
        self.rejected("observation_record_mismatch")

    def test_reference_ordinals_and_records_cannot_be_missing_extra_reordered_or_forged(self):
        original = copy.deepcopy(self.packet["reference_verification"]["results"])
        self.assertGreater(len(original), 1)
        for records, code in (
            (original[:-1], "reference_missing"),
            (original + [original[0]], "reference_extra"),
            (original[::-1], "reference_order_mismatch"),
            ([original[0]] * len(original), "reference_identity_mismatch"),
        ):
            self.packet["reference_verification"]["results"] = records
            self.rejected(code)
        self.packet["reference_verification"]["results"] = original
        original[0]["source_sha256"] = "0" * 64
        self.rejected("reference_record_mismatch")

    def test_source_hashes_slices_and_rehashed_source_tampering(self):
        for field in ("input_sha256", "text_sha256"):
            self.packet = copy.deepcopy(self.packets["history"])
            self.packet["source"][field] = "0" * 64
            self.rejected("source_digest_mismatch")
        self.packet = copy.deepcopy(self.packets["intake-1"])
        self.packet["source"]["start"] += 1
        self.rejected("source_slice_mismatch", key="intake-1")
        self.packet = copy.deepcopy(self.packets["history"])
        self.packet["source"]["input_text"] += " "
        self.packet["source"]["input_sha256"] = sha256(
            self.packet["source"]["input_text"].encode()
        ).hexdigest()
        self.rejected("source_identity_mismatch")

    def test_exact_crlf_and_combining_unicode_survive_and_normalization_fails(self):
        key = "batch-synthetic-csv-1"
        self.packet = copy.deepcopy(self.packets[key])
        self.assertIn("\r\n", self.packet["intake"]["question"])
        self.assertIn("e\u0301", self.packet["intake"]["question"])
        self.verify(key=key)
        self.packet["intake"]["question"] = self.packet["intake"]["question"].replace(
            "e\u0301", "é"
        )
        self.rejected("packet_replay_mismatch", key=key)

    def test_manifest_membership_missing_extra_order_and_duplicate(self):
        original = copy.deepcopy(self.manifest["case_inputs"])
        for records, code in (
            (original[:-1], "manifest_missing"),
            (original + [original[0]], "manifest_extra"),
            (original[::-1], "manifest_order_mismatch"),
            ([original[0], original[0], *original[2:]], "manifest_identity_mismatch"),
        ):
            self.manifest["case_inputs"] = records
            self.rejected(code)

    def test_manifest_packet_digest_and_source_membership(self):
        member = next(
            m for m in self.manifest["case_inputs"] if m["identity"]["case_key"] == "history"
        )
        member["packet_sha256"] = "0" * 64
        self.rejected("packet_digest_mismatch")
        member["packet_sha256"] = sha256(serialize_packet(self.packet)).hexdigest()
        member["source_text_sha256"] = "0" * 64
        self.rejected("manifest_member_mismatch")

    def test_manifest_full_replay_rejects_other_member_or_file_digest_tampering(self):
        self.manifest["files"]["report.json"]["sha256"] = "0" * 64
        self.rejected("manifest_replay_mismatch")
        self.manifest = json.loads(self.bundle.file("manifest.json"))
        self.manifest["case_inputs"][0]["packet_sha256"] = "0" * 64
        self.rejected("manifest_replay_mismatch")

    def test_coordinated_rehash_cannot_replace_authoritative_fixture(self):
        self.packet["snapshots"][0]["answer"] = "fabricated tampering"
        member = next(
            m for m in self.manifest["case_inputs"] if m["identity"]["case_key"] == "history"
        )
        member["packet_sha256"] = sha256(serialize_packet(self.packet)).hexdigest()
        self.rejected("revision_digest_mismatch")

    def test_unrecognized_fields_and_claimed_approval_fail_closed(self):
        self.packet["extra"] = None
        self.rejected("packet_fields_mismatch")
        del self.packet["extra"]
        self.packet["scholarly_decision"] = "approved"
        self.rejected("packet_replay_mismatch")

    def test_wire_decoder_rejects_invalid_unicode_duplicate_keys_and_noncanonical_json(self):
        from apps.fast8_packet_verifier.services import PacketVerificationError, verify_packet

        for raw, code in (
            (b"\xff", "invalid_utf8"),
            (b'{"x":"\\ud800"}\n', "invalid_utf8"),
            (b'{"x":1,"x":2}\n', "duplicate_key"),
            (b'{"x":NaN}\n', "invalid_json"),
            (b'{"x":1.5}\n', "unsupported_value"),
            (b"[1]\n", "invalid_payload"),
            (b"{}", "noncanonical_packet"),
            (b'{"x":' * 2000 + b"null" + b"}" * 2000, "structure_limit"),
            (b" " * (MAX_PACKET_BYTES + 1), "byte_limit"),
            ("{}", "invalid_input_type"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(PacketVerificationError) as caught:
                    verify_packet(
                        raw,
                        self.bundle.file("manifest.json"),
                        case_key="history",
                        synthetic_fixtures_only=True,
                    )
                self.assertEqual(caught.exception.code, "packet_verify: " + code)

    def test_guard_runs_before_decoding_and_no_file_network_or_persistence_io(self):
        from apps.fast8_packet_verifier.services import PacketVerificationError, verify_packet

        for flag, env in ((False, "0"), (1, "0"), (True, "1")):
            with patch.dict(os.environ, {"FATWA_PRODUCTION": env}):
                with self.assertRaises(PacketVerificationError) as caught:
                    verify_packet(None, None, case_key="history", synthetic_fixtures_only=flag)
                self.assertEqual(caught.exception.code, "packet_verify: synthetic_development_only")
        with (
            patch("builtins.open", side_effect=AssertionError("filesystem")),
            patch("socket.socket", side_effect=AssertionError("network")),
            patch(
                "apps.intake_workflow.review.load_review_worklist",
                side_effect=AssertionError("persistence"),
            ),
        ):
            self.verify()

    def test_export_authority_still_rejects_tampering(self):
        from apps.editorial_export.services import ExportError

        files = dict(self.bundle.files)
        files["manifest.json"] += b" "
        with self.assertRaisesRegex(ExportError, "export: replay_mismatch"):
            verify_export(files, synthetic_fixtures_only=True)

    def test_nested_contract_types_fail_closed(self):
        for field, value in (
            ("source", None),
            ("snapshots", {}),
            ("snapshots", [None]),
            ("reference_verification", []),
        ):
            self.packet = copy.deepcopy(self.packets["history"])
            self.packet[field] = value
            self.rejected("invalid_contract")
        self.packet = copy.deepcopy(self.packets["history"])
        del self.packet["snapshots"][0]["number"]
        self.rejected("invalid_contract")

    def test_manifest_decoder_and_inherited_bounds_fail_closed(self):
        from apps.editorial_export.services import MAX_FILE_BYTES
        from apps.fast8_packet_verifier.services import PacketVerificationError, verify_packet

        for raw, code in (
            (b"\xff", "invalid_utf8"),
            (b"{}", "noncanonical_manifest"),
            (b'{"x":1,"x":2}\n', "duplicate_key"),
            (b" " * (MAX_FILE_BYTES + 1), "byte_limit"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(PacketVerificationError) as caught:
                    verify_packet(
                        serialize_packet(self.packet),
                        raw,
                        case_key="history",
                        synthetic_fixtures_only=True,
                    )
                self.assertEqual(caught.exception.code, "packet_verify: " + code)
        for value, code in (
            ({"text": "x" * 131073}, "text_limit"),
            ({"items": [None] * 4097}, "structure_limit"),
            ({"number": 2**63}, "integer_limit"),
        ):
            raw = (json.dumps(value) + "\n").encode()
            with self.subTest(code=code):
                with self.assertRaises(PacketVerificationError) as caught:
                    verify_packet(
                        raw,
                        self.bundle.file("manifest.json"),
                        case_key="history",
                        synthetic_fixtures_only=True,
                    )
                self.assertEqual(caught.exception.code, "packet_verify: " + code)

    def test_fixture_failure_is_not_a_partial_verification(self):
        from apps.editorial_export.services import ExportError

        with patch(
            "apps.editorial_export.services.build_export",
            side_effect=ExportError("synthetic failure"),
        ):
            self.rejected("fixture_replay_unavailable")

    def test_nondefault_selection_is_not_manifest_member(self):
        from apps.editorial_workbench.packets import build_packet
        from apps.editorial_workbench.services import build_cases

        history = next(c for c in build_cases() if c.key == "history")
        self.rejected(
            "packet_replay_mismatch",
            packet=build_packet(history, revision="7", before="11", after="4").payload(),
        )
