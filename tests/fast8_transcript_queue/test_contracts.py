"""Fail closed on drift between actual upstream contracts, without loose joins."""

import json
import unittest
from unittest.mock import patch

from apps.fast8_transcript_queue import services
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch
from apps.transcript_pipeline import TranscriptBatch, segment_file
from tests.fast8_transcript_queue.test_services import encode, segments


class ContractBoundaryTests(unittest.TestCase):
    def test_missing_reused_and_mismatched_segment_references_are_rejected(self):
        raw = encode(segments())
        original = segment_file(raw, ".json", synthetic_fixtures_only=True)

        def missing(report):
            report["pairs"][0]["question_segment_id"] = "absent"

        def wrong_kind(report):
            report["pairs"][0]["answer_segment_id"] = "q1"

        def missing_source(report):
            report["sources"].clear()

        def wrong_revision(report):
            report["pairs"][0]["source_sha256"] = "0" * 64

        def unattached_answer(report):
            report["pairs"][0]["answer_segment_id"] = None

        def ambiguous_segment(report):
            report["segments"].append(report["segments"][0])

        def ambiguous_source(report):
            report["sources"].append(report["sources"][0])

        def wrong_file(report):
            report["input_sha256"] = "0" * 64

        def wrong_prepared(report):
            report["preparation"]["export_sha256"] = "0" * 64

        # Inject narrow contract drift into complete real service outputs.
        for mutate in (
            missing,
            wrong_kind,
            missing_source,
            wrong_revision,
            unattached_answer,
            ambiguous_segment,
            ambiguous_source,
            wrong_file,
            wrong_prepared,
        ):
            report = json.loads(original.json_bytes())
            mutate(report)
            changed = TranscriptBatch(json.dumps(report).encode(), original.prepared_bytes())
            with (
                self.subTest(mutation=mutate.__name__),
                patch.object(services, "segment_file", return_value=changed),
                self.assertRaises(ValidationError),
            ):
                services.build_transcript_queue(raw, ".json", synthetic_fixtures_only=True)

    def test_preparation_drift_never_reassigns_questions_by_row_or_external_id(self):
        raw = encode(segments())
        original = segment_file(raw, ".json", synthetic_fixtures_only=True)

        def missing(report):
            report["items"].clear()

        def wrong_identity(report):
            report["items"][0]["original"]["external_id"] = "unrelated"

        def wrong_question(report):
            report["items"][0]["original"]["question"] = "unrelated fabricated question"

        def invented_link(report):
            report["items"][0]["original"]["prepared_clip_url"] = "https://example.invalid/clip"

        def invalid(report):
            report["items"][0]["statuses"] = ["blocked-invalid"]

        for mutate in (missing, wrong_identity, wrong_question, invented_link, invalid):
            prepared = prepare_batch(original.prepared_bytes(), synthetic_fixtures_only=True)
            mutate(prepared.report)
            with (
                self.subTest(mutation=mutate.__name__),
                patch.object(services, "prepare_batch", return_value=prepared),
                self.assertRaises(ValidationError),
            ):
                services.build_transcript_queue(raw, ".json", synthetic_fixtures_only=True)

    def test_reused_pair_identity_does_not_join_different_sources(self):
        raw = encode(segments() + [dict(row, source_id="second") for row in segments()])
        original = segment_file(raw, ".json", synthetic_fixtures_only=True)
        report = json.loads(original.json_bytes())
        report["pairs"][1] = report["pairs"][0]
        prepared = prepare_batch(original.prepared_bytes(), synthetic_fixtures_only=True)
        prepared.report["items"][1]["original"] = prepared.report["items"][0]["original"]
        changed = TranscriptBatch(json.dumps(report).encode(), original.prepared_bytes())
        with (
            patch.object(services, "segment_file", return_value=changed),
            patch.object(services, "prepare_batch", return_value=prepared),
            self.assertRaisesRegex(ValidationError, "ambiguous_pair_identity"),
        ):
            services.build_transcript_queue(raw, ".json", synthetic_fixtures_only=True)
