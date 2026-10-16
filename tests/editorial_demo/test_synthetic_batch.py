"""E2 reusable composition and allowlisted worklist, synthetic and database-free."""
from copy import deepcopy
from dataclasses import replace
import json
import socket
import sqlite3
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from apps.editorial_demo import integration
from apps.fatwa_drafts.intake import ValidationError


def encode(items):
    return json.dumps({"schema": integration.SCHEMA, "items": items}, ensure_ascii=False).encode()


class SyntheticBatchTests(SimpleTestCase):
    def compose(self, items=None, raw=None, **kwargs):
        function = getattr(integration, "compose_synthetic_batch", None)
        self.assertTrue(callable(function), "Reusable synthetic batch callable is missing")
        mapping, bridge, catalog = integration._synthetic_dependencies()
        return function(raw if raw is not None else encode(items),
                        reference_map=mapping, bridge_config=bridge, catalog=catalog, **kwargs)

    def fresh(self, ident="UNSEEN-619"):
        row = deepcopy(integration._SYNTHETIC_ROWS[0])
        row.update(external_id=ident, question="  سُؤَالٌ جديد\tبِعلاماته\nوسطره  ")
        return row

    def test_unseen_id_and_exact_question_without_io(self):
        item = self.fresh()
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
             patch.object(sqlite3, "connect", side_effect=AssertionError("database forbidden")):
            rows = self.compose([item], synthetic_fixtures_only=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].external_id, item["external_id"])
        self.assertEqual(rows[0].question, item["question"])
        self.assertTrue(rows[0].draft_created)
        self.assertEqual(rows[0].references[0].status, "verified")

    def test_acknowledgement_rejected_before_processing(self):
        with patch.object(integration, "prepare_batch", side_effect=AssertionError("processing forbidden")):
            for kwargs in ({}, {"synthetic_fixtures_only": False}, {"synthetic_fixtures_only": 1}):
                with self.assertRaisesRegex(ValidationError, "acknowledgement_required"):
                    self.compose(raw=object(), **kwargs)

    def test_wrapper_keeps_duplicate_and_malformed_blocked_rows_visible(self):
        good = self.fresh()
        duplicate = self.fresh("DUPLICATE")
        malformed = self.fresh("BAD-LINK")
        malformed["reference_links"] = [{"source_id": 19, "heading_id": None}]
        items = (good, duplicate, deepcopy(duplicate), malformed, 7)
        with patch.object(integration, "_SYNTHETIC_ROWS", items):
            rows = integration.build_preview_rows()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0].status, "ready-for-editor")
        for row in rows[1:]:
            self.assertEqual(row.status, "blocked-invalid")
            self.assertFalse(row.draft_created)
            self.assertTrue(all(ref.citation is None for ref in row.references))

    def test_mixed_media_missing_map_and_blocked_rows(self):
        valid, missing, invalid, unmapped = [self.fresh(str(i)) for i in range(4)]
        missing["prepared_clip_url"] = ""
        invalid["prepared_clip_url"] = "https://example.invalid:8443/media.mp4"
        unmapped["reference_links"] = [{"source_id": "unseen-source", "heading_id": "unseen-heading"}]
        rows = self.compose([valid, missing, invalid, unmapped], synthetic_fixtures_only=True)
        self.assertEqual([row.status for row in rows], [
            "ready-for-editor", "needs-editor-review", "blocked-invalid", "needs-editor-review"])
        self.assertEqual([row.draft_created for row in rows], [True, False, False, True])
        self.assertEqual(rows[1].prepared_clip_url, "")
        self.assertIsNone(rows[3].references[0].citation)

    def test_source_mapping_disagreement_suppresses_citation(self):
        function = getattr(integration, "compose_synthetic_batch", None)
        self.assertTrue(callable(function), "Reusable synthetic batch callable is missing")
        mapping, bridge, catalog = integration._synthetic_dependencies()
        key = next(iter(mapping))
        mapping[key] = replace(mapping[key], c2=replace(mapping[key].c2, edition_key="different-edition"))
        rows = function(encode([self.fresh()]), synthetic_fixtures_only=True,
                        reference_map=mapping, bridge_config=bridge, catalog=catalog)
        self.assertEqual(rows[0].status, "needs-editor-review")
        self.assertIn("reference_mismatch", rows[0].issue_codes)
        self.assertIsNone(rows[0].references[0].citation)

    def test_untrusted_envelopes_and_bounds_reject(self):
        bad = [b'{"schema":"fatwa.prepared-intake.v1","items":[],"reference_map":{}}',
               b'{"schema":"fatwa.prepared-intake.v1","items":[],"items":[]}',
               b'\xff', b' ' * 1_000_001, encode([]), encode([self.fresh()] * 1001),
               b'{"schema":"fatwa.prepared-intake.v1","items":["\\ud800"]}']
        huge = self.fresh()
        huge["reference_links"] *= 101
        bad.append(encode([huge]))
        with patch.object(integration, "prepare_batch", side_effect=AssertionError("processing forbidden")):
            for raw in bad:
                with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                    self.compose(raw=raw, synthetic_fixtures_only=True)

    def test_repeated_calls_do_not_retain_batches_or_modify_configuration(self):
        first, second = self.fresh(), self.fresh()
        second["question"] = "نص اصطناعي مستقل للمعرّف نفسه"
        before = deepcopy(first)
        result = self.compose([first], synthetic_fixtures_only=True)
        other = self.compose([second], synthetic_fixtures_only=True)
        self.assertNotEqual(result[0].question, other[0].question)
        self.assertEqual(result, self.compose([first], synthetic_fixtures_only=True))
        self.assertEqual(first, before)


class BatchWorklistTests(SimpleTestCase):
    url = "/dev/editorial-preview/pipeline"

    def get(self, suffix=""):
        return self.client.get(self.url + suffix, HTTP_HOST="localhost")

    def test_same_external_id_is_isolated_by_allowlisted_batch(self):
        baseline = self.get("/SYN-P01")
        alternate = self.get("/SYN-P01?batch=mixed")
        self.assertEqual(alternate.status_code, 200)
        self.assertNotEqual(baseline.context["row"].question, alternate.context["row"].question)
        self.assertEqual(alternate.context["batch"], "mixed")
        self.assertContains(alternate, "دفعة متنوعة")

    def test_batch_filter_page_and_return_state(self):
        query = "?batch=mixed&status=blocked-invalid&issue=invalid_input&page_size=1&page=2&q=اصطناعي"
        response = self.get(query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rows"]), 1)
        row = response.context["rows"][0]
        detail = self.get("/" + row.external_id + query)
        self.assertEqual(detail.status_code, 200)
        params = parse_qs(detail.context["filter_query"])
        self.assertEqual(params, {"batch": ["mixed"], "status": ["blocked-invalid"], "issue": ["invalid_input"],
                                 "page_size": ["1"], "page": ["2"], "q": ["اصطناعي"]})
        self.assertEqual(detail.context["row"], row)
        returned = self.get("?" + detail.context["filter_query"])
        self.assertEqual(returned.context["rows"], response.context["rows"])
        self.assertEqual(parse_qs(urlsplit(response.context["previous_url"]).query)["batch"], ["mixed"])

    def test_invalid_batch_rejects_before_composition(self):
        with patch("apps.editorial_demo.views.build_preview_rows", side_effect=AssertionError("forbidden")):
            for suffix in ("?batch=../private", "?batch=/tmp/input.json", "?batch=default&batch=mixed",
                           "?batch=unknown", "?batch=", "?raw=private"):
                self.assertEqual(self.get(suffix).status_code, 400)

    def test_selected_batch_is_read_only_and_original_whitespace_visible(self):
        response = self.get("/SYN-P01?batch=mixed")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="original-text"')
        self.assertNotContains(response, "<textarea")
        self.assertNotContains(response, "<video")
        self.assertNotContains(response, 'href="https:')
        self.assertEqual(self.client.post(self.url + "?batch=mixed", HTTP_HOST="localhost").status_code, 405)
        self.assertEqual(self.client.head(self.url + "?batch=mixed", HTTP_HOST="localhost").content, b"")
