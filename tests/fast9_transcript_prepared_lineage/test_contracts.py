"""Narrow fault injection into real service outputs checks stage drift boundaries."""

import json
import unittest
from unittest.mock import patch

from apps.fast8_segment_timeline.service import TimelineReport, diagnose_file
from apps.fast8_transcript_queue.services import build_transcript_queue
from apps.fast9_transcript_prepared_lineage import services
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch
from tests.fast9_transcript_prepared_lineage.support import FIXTURES, arguments


class StageContractTests(unittest.TestCase):
    def setUp(self):
        self.raw = (FIXTURES / "manual-qa.json").read_bytes()
        self.kwargs = arguments(self.raw)
        self.timeline = diagnose_file(self.raw, ".json", synthetic_fixtures_only=True)

    def assert_bad_timeline(self, cues, report=None, code="cue_origin_mismatch"):
        altered = TimelineReport(
            self.timeline.json_bytes() if report is None else json.dumps(report).encode(),
            json.dumps(cues, ensure_ascii=False).encode(),
        )
        with (
            patch.object(services, "diagnose_file", return_value=altered),
            self.assertRaisesRegex(ValidationError, code),
        ):
            services.build_lineage(self.raw, ".json", **self.kwargs)

    def test_cue_origin_text_hash_and_timing_drift(self):
        for field, value in (
            ("source_sha256", "0" * 64),
            ("segment_sha256", "0" * 64),
            ("pair_id", "other"),
            ("kind", "answer"),
            ("start_ms", 18),
            ("end_ms", 1018),
            ("question_label", "unrelated synthetic label"),
            ("start_time", "23:59:59.999"),
            ("end_time", "00:00:01.018"),
        ):
            with self.subTest(field=field):
                cues = json.loads(self.timeline.cue_json_bytes())
                cues["cues"][0][field] = value
                self.assert_bad_timeline(cues)

    def test_missing_duplicate_extra_and_cross_source_cues(self):
        original = json.loads(self.timeline.cue_json_bytes())
        missing = json.loads(self.timeline.cue_json_bytes())
        missing["cues"].pop()
        duplicate = json.loads(self.timeline.cue_json_bytes())
        duplicate["cues"].append(duplicate["cues"][0])
        extra = json.loads(self.timeline.cue_json_bytes())
        extra["cues"].append(dict(extra["cues"][0], segment_id="unrelated"))
        crossed = json.loads(self.timeline.cue_json_bytes())
        crossed["cues"][0]["source_sha256"] = original["cues"][2]["source_sha256"]
        for cues, code in (
            (missing, "missing_or_reused_cue"),
            (duplicate, "duplicate_cue"),
            (extra, "unjoined_cue"),
            (crossed, "cue_origin_mismatch"),
        ):
            with self.subTest(code=code):
                self.assert_bad_timeline(cues, code=code)

    def test_timeline_source_and_input_revision_drift(self):
        for field, value, code in (
            ("input_sha256", "0" * 64, "timeline_identity_mismatch"),
            ("sources", [], "timeline_source_mismatch"),
            ("contract_status", "NOT_RUN", "timeline_identity_mismatch"),
        ):
            report = json.loads(self.timeline.json_bytes())
            report[field] = value
            with self.subTest(field=field):
                self.assert_bad_timeline(json.loads(self.timeline.cue_json_bytes()), report, code)

    def test_prepared_replay_drift_cannot_join_stock_case_or_normalize_text(self):
        queue = build_transcript_queue(self.raw, ".json", synthetic_fixtures_only=True)
        for field, value in (
            ("external_id", "fixed-stock-20"),
            ("question", "unrelated synthetic question"),
            ("prepared_clip_url", "https://example.invalid/clip"),
        ):
            prepared = prepare_batch(queue.prepared_bytes(), synthetic_fixtures_only=True)
            prepared.report["items"][0]["original"][field] = value
            with (
                self.subTest(field=field),
                patch.object(services, "prepare_batch", return_value=prepared),
                self.assertRaisesRegex(ValidationError, "prepared_stage_mismatch"),
            ):
                services.build_lineage(self.raw, ".json", **self.kwargs)
