"""Cross-adapter regressions using original APIs and explicitly fabricated bytes."""

import base64
import codecs
import hashlib
import json
import unicodedata
import unittest

from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_file
from apps.prepared_pipeline.batches import PreparedInput, prepare_batches
from apps.prepared_pipeline.diagnostics import diagnose_batches
from apps.transcript_pipeline import segment_file
from tools.content_intake.cli import artifacts
from tools.fast8_ingest_adversarial.fixtures import (
    FORMATS,
    MARKER,
    ORIGINAL,
    encode,
    intake_row,
    segment_row,
)


class BoundaryTests(unittest.TestCase):
    def test_bom_crlf_exact_text_and_original_file_and_row_bytes(self):
        for suffix in FORMATS:
            with self.subTest(format=suffix):
                row = intake_row()
                raw = encode([row], suffix)
                outputs, manifest = artifacts(raw, suffix)
                batch = prepare_file(raw, suffix, synthetic_fixtures_only=True)
                report = diagnose_batches(
                    [PreparedInput("SYN-file", raw, suffix)], synthetic_fixtures_only=True
                ).report
                self.assertEqual(manifest["status"], "VALID")
                self.assertEqual(json.loads(outputs["intake.json"])["items"], [row])
                self.assertEqual(batch.drafts[0].intake.question.encode(), ORIGINAL.encode())
                self.assertEqual(batch.drafts[0].intake.staff_notes, row["staff_notes"])
                source = report["inputs"][0]
                self.assertEqual(base64.b64decode(source["raw_base64"]), raw)
                self.assertEqual(source["byte_length"], len(raw))
                sha = hashlib.sha256(raw).hexdigest()
                self.assertEqual(source["input_sha256"], sha)
                self.assertEqual(manifest["input_sha256"], sha)
                self.assertEqual(batch.report["input_sha256"], sha)
                span = report["rows"][0]["provenance"]
                # Compare to independently framed one-record bytes, not only self-reported offsets.
                body = raw[len(codecs.BOM_UTF8) :]
                expected = (
                    body.split(b"\r\n", 1)[1]
                    if suffix == ".csv"
                    else body[body.index(b"{") : body.rindex(b"}") + 1]
                    if suffix == ".json"
                    else body
                )
                self.assertEqual(base64.b64decode(span["raw_base64"]), expected)
                self.assertEqual(raw[span["byte_start"] : span["byte_end"]], expected)
                self.assertEqual(
                    report["rows"][0]["row_id"],
                    f"{sha}:{span['byte_start']}:{span['byte_end']}",
                )

    def test_unicode_equivalent_ids_and_text_are_not_normalized_or_merged(self):
        composed, decomposed = "SYN-أ", "SYN-ا\u0654"
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(unicodedata.normalize("NFC", decomposed), composed)
        for suffix in FORMATS:
            with self.subTest(format=suffix):
                rows = [
                    intake_row(composed, question="أ\r\n"),
                    intake_row(decomposed, question="ا\u0654\r\n"),
                ]
                raw = encode(rows, suffix)
                outputs, manifest = artifacts(raw, suffix)
                self.assertEqual(manifest["status"], "VALID")
                self.assertEqual(json.loads(outputs["intake.json"])["items"], rows)
                batch = prepare_file(raw, suffix, synthetic_fixtures_only=True)
                self.assertEqual(
                    [d.intake.external_id for d in batch.drafts], [composed, decomposed]
                )
                self.assertEqual(
                    [d.intake.question for d in batch.drafts], [r["question"] for r in rows]
                )
                sources = [segment_row(source_id=identity) for identity in (composed, decomposed)]
                transcript = segment_file(
                    encode(sources, suffix), suffix, synthetic_fixtures_only=True
                )
                self.assertEqual(json.loads(transcript.json_bytes())["segments"], sources)
                self.assertEqual(len(json.loads(transcript.prepared_bytes())["items"]), 2)

    def test_semantically_identical_file_framing_changes_only_input_digest(self):
        for suffix in FORMATS:
            with self.subTest(format=suffix):
                raw = encode([intake_row()], suffix)
                # Removing the BOM changes no parsed fields, including embedded CRLF.
                changed = raw[len(codecs.BOM_UTF8) :]
                first, first_manifest = artifacts(raw, suffix)
                second, second_manifest = artifacts(changed, suffix)
                self.assertEqual(first, second)
                self.assertNotEqual(first_manifest["input_sha256"], second_manifest["input_sha256"])
                one = diagnose_batches(
                    [PreparedInput("s", raw, suffix)], synthetic_fixtures_only=True
                )
                two = diagnose_batches(
                    [PreparedInput("s", changed, suffix)], synthetic_fixtures_only=True
                )
                self.assertNotEqual(
                    one.report["rows"][0]["row_id"], two.report["rows"][0]["row_id"]
                )

    def test_escaped_duplicate_json_keys_reject_complete_file_including_valid_prefix(self):
        for suffix in (".json", ".jsonl"):
            for key in ("external_id", "source_id"):
                with self.subTest(format=suffix, key=key):
                    first = json.dumps(intake_row() if key == "external_id" else segment_row())
                    escaped_key = "\\u%04x" % ord(key[0]) + key[1:]
                    bad = '{"%s":"%s","%s":"other"}' % (key, MARKER, escaped_key)
                    text = (
                        "[" + first + "," + bad + "]" if suffix == ".json" else first + "\r\n" + bad
                    )
                    raw = codecs.BOM_UTF8 + text.encode()
                    with self.assertRaises(ValueError):
                        artifacts(raw, suffix)
                    for adapter in (prepare_file, segment_file):
                        with self.assertRaises(ValidationError) as error:
                            adapter(raw, suffix, synthetic_fixtures_only=True)
                        self.assertEqual(str(error.exception), "input: malformed_or_over_limit")
                        self.assertNotIn(MARKER, str(error.exception))

    def test_duplicate_key_in_csv_reference_cell_blocks_row_without_losing_original(self):
        cell = '[{"source_id":"SYN-a","\\u0073ource_id":"SYN-b","heading_id":"h"}]'
        raw = encode([intake_row(reference_links=cell)], ".csv")
        outputs, manifest = artifacts(raw, ".csv")
        self.assertEqual(manifest["status"], "INVALID")
        self.assertEqual(json.loads(outputs["intake.json"])["items"], [])
        self.assertIn(
            "expected_source_id_heading_id_string_pairs", [f["code"] for f in manifest["findings"]]
        )
        batch = prepare_file(raw, ".csv", synthetic_fixtures_only=True)
        self.assertEqual(batch.drafts, ())
        self.assertEqual(batch.report["items"][0]["original"]["reference_links"], cell)
        self.assertIn("blocked-invalid", batch.report["items"][0]["statuses"])

    def test_invalid_utf8_after_valid_prefix_never_yields_partial_acceptance(self):
        for suffix in FORMATS:
            intake = encode(
                [intake_row("SYN-first"), intake_row("SYN-second", question=MARKER)], suffix
            )
            transcript = encode(
                [segment_row(), segment_row(source_id="SYN-second", text=MARKER)], suffix
            )
            # Positive controls are valid for each real schema before byte corruption.
            self.assertEqual(artifacts(intake, suffix)[1]["valid_row_count"], 2)
            self.assertEqual(
                len(prepare_file(intake, suffix, synthetic_fixtures_only=True).drafts), 2
            )
            control = segment_file(transcript, suffix, synthetic_fixtures_only=True)
            self.assertEqual(len(json.loads(control.json_bytes())["segments"]), 2)
            for tail in (b"\xff", b"\xd8", b"\xc0\xaf", b"\xed\xa0\x80"):
                with self.subTest(format=suffix, tail=tail.hex()):
                    # Corrupt inside the second text cell/string: lossy decoding would
                    # leave syntactically valid input, so syntax errors cannot mask it.
                    raw = intake.replace(MARKER.encode(), MARKER.encode() + tail)
                    with self.assertRaises(UnicodeError):
                        artifacts(raw, suffix)
                    for adapter, source in ((prepare_file, intake), (segment_file, transcript)):
                        corrupt = source.replace(MARKER.encode(), MARKER.encode() + tail)
                        with self.assertRaisesRegex(
                            ValidationError, "^input: malformed_or_over_limit$"
                        ):
                            adapter(corrupt, suffix, synthetic_fixtures_only=True)

    def test_multibyte_cell_exact_limit_and_plus_one_remain_lossless(self):
        exact = ORIGINAL + "ع" * (20000 - len(ORIGINAL))
        too_long = exact + "ع"
        self.assertGreater(len(exact.encode()), 20000)
        for suffix in FORMATS:
            with self.subTest(format=suffix):
                raw = encode(
                    [
                        intake_row("SYN-good", question=exact),
                        intake_row("SYN-bad", question=too_long),
                    ],
                    suffix,
                )
                outputs, manifest = artifacts(raw, suffix)
                self.assertEqual((manifest["row_count"], manifest["valid_row_count"]), (2, 1))
                self.assertEqual(manifest["status"], "INVALID")
                self.assertIn(
                    {
                        "row": 2,
                        "field": "question",
                        "code": "too_long_max_20000",
                        "severity": "error",
                    },
                    manifest["findings"],
                )
                self.assertEqual(json.loads(outputs["intake.json"])["items"][0]["question"], exact)
                batch = prepare_file(raw, suffix, synthetic_fixtures_only=True)
                self.assertEqual([d.intake.question for d in batch.drafts], [exact])
                self.assertEqual(batch.report["items"][1]["original"]["question"], too_long)
                accepted = segment_file(
                    encode([segment_row(text=exact)], suffix), suffix, synthetic_fixtures_only=True
                )
                self.assertEqual(json.loads(accepted.json_bytes())["segments"][0]["text"], exact)
                with self.assertRaises(ValidationError):
                    segment_file(
                        encode([segment_row(text=too_long)], suffix),
                        suffix,
                        synthetic_fixtures_only=True,
                    )

    def test_cross_format_duplicate_invalid_late_row_revokes_all_duplicate_receipts(self):
        inputs = [
            PreparedInput("SYN-first", encode([intake_row("SYN-duplicate")], ".csv"), ".csv"),
            PreparedInput("SYN-malformed", b"\xff", ".json"),
            PreparedInput(
                "SYN-late", encode([intake_row("SYN-duplicate", question="")], ".jsonl"), ".jsonl"
            ),
            PreparedInput("SYN-unique", encode([intake_row("SYN-unique")], ".json"), ".json"),
        ]
        collection = prepare_batches(inputs, synthetic_fixtures_only=True)
        self.assertTrue(collection.has_errors)
        self.assertEqual(
            [b.report()["status"] for b in collection.batches],
            ["BLOCKED", "ERROR", "BLOCKED", "READY"],
        )
        self.assertEqual(collection.batches[1].error_code, "MALFORMED_INPUT")
        for index in (0, 2):
            batch = collection.batches[index].batch
            self.assertEqual(batch.drafts, ())
            self.assertIsNone(batch.report["items"][0]["draft"])
            self.assertIn("duplicate_id", [f["code"] for f in batch.report["items"][0]["findings"]])
        self.assertEqual(collection.workbench_summary()["draft_count"], 1)
        report = diagnose_batches(inputs, synthetic_fixtures_only=True).report
        self.assertEqual(len(report["duplicate_groups"]), 1)
        self.assertEqual(len(report["duplicate_groups"][0]["locations"]), 2)
        for item, source in zip(inputs, report["inputs"], strict=True):
            self.assertEqual(base64.b64decode(source["raw_base64"]), item.raw)
            self.assertEqual(source["input_sha256"], hashlib.sha256(item.raw).hexdigest())

    def test_source_inventory_rejects_literal_duplicates_but_keeps_unicode_variants(self):
        inputs = [PreparedInput("SYN-file", encode([intake_row()], ".json"), ".json")]
        with self.assertRaisesRegex(ValidationError, "^source_ids: duplicate_id$"):
            diagnose_batches(
                inputs, synthetic_fixtures_only=True, available_source_ids=["SYN-أ"] * 2
            )
        result = diagnose_batches(
            inputs, synthetic_fixtures_only=True, available_source_ids=["SYN-أ", "SYN-ا\u0654"]
        )
        self.assertFalse(result.has_errors)


if __name__ == "__main__":
    unittest.main()
