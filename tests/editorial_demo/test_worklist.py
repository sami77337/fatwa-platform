"""Worklist acceptance and fault injection over the real D1/D3 composition.

All fixtures are synthetic. No database/network or human approval is simulated.
"""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings

from apps.editorial_demo import integration
from apps.reference_links.resolution import SnapshotCatalog


class WorklistTests(SimpleTestCase):
    url = "/dev/editorial-preview/pipeline"

    def get(self, suffix="", **kwargs):
        return self.client.get(self.url + suffix, HTTP_HOST="localhost", **kwargs)

    def altered_reference(self, **changes):
        real_resolve = integration.resolve_prepared_pointers

        def altered(*args, **kwargs):
            rows = real_resolve(*args, **kwargs)
            first = replace(rows[0].reference_links[0], **changes)
            return (replace(rows[0], reference_links=(first,)), *rows[1:])

        return patch.object(integration, "resolve_prepared_pointers", side_effect=altered)

    def actual_evidence(self):
        return integration._synthetic_dependencies()[2].lookup(41, 73)[0]

    def assert_unverified(self, row):
        self.assertEqual(row.status, "needs-editor-review")
        self.assertEqual(row.references[0].status, "unverified")
        self.assertIsNone(row.references[0].citation)
        self.assertIn("reference_mismatch", getattr(row, "issue_codes", ()))

    def test_two_verified_flags_cannot_hide_a_different_original_pointer(self):
        with self.altered_reference(original_pointer=(("source_id", "wrong-source"), ("heading_id", "wrong-heading"))):
            self.assert_unverified(integration.build_preview_rows()[0])

    def test_two_verified_flags_cannot_hide_a_different_source_row(self):
        with self.altered_reference(evidence=replace(self.actual_evidence(), source_row_id=74)):
            self.assert_unverified(integration.build_preview_rows()[0])

    def test_two_verified_flags_cannot_hide_changed_reference_text(self):
        changed = replace(self.actual_evidence(), heading_title="عنوان مختلف", path=("كتاب الطهارة", "عنوان مختلف"))
        with self.altered_reference(evidence=changed):
            self.assert_unverified(integration.build_preview_rows()[0])

    def test_verified_without_evidence_is_not_displayed(self):
        with self.altered_reference(evidence=None):
            self.assert_unverified(integration.build_preview_rows()[0])

    def test_display_citation_is_derived_from_matched_evidence_not_adapter_markup(self):
        with self.altered_reference(citation="WRONG_CITATION<script>bad</script>"):
            row = integration.build_preview_rows()[0]
        self.assertNotIn("WRONG_CITATION", row.references[0].citation or "")
        self.assertIn("باب تجريبي للطهارة", row.references[0].citation or "")

    def test_archive_pin_disagreement_never_verifies(self):
        real_prepare = integration.prepare_batch

        def altered(*args, **kwargs):
            batch = real_prepare(*args, **kwargs)
            report = deepcopy(batch.report)
            report["items"][0]["references"][0]["mapping"]["c2"]["source_archive_sha256"] = "c" * 64
            return replace(batch, report=report)

        with patch.object(integration, "prepare_batch", side_effect=altered):
            self.assert_unverified(integration.build_preview_rows()[0])

    def test_missing_non_draft_row_cannot_silently_change_original_question(self):
        real_prepare = integration.prepare_batch

        def altered(*args, **kwargs):
            batch = real_prepare(*args, **kwargs)
            report = deepcopy(batch.report)
            report["items"][2]["original"]["question"] = "not the received question"
            return replace(batch, report=report)

        with patch.object(integration, "prepare_batch", side_effect=altered):
            with self.assertRaises(ValueError):
                integration.build_preview_rows()

    def test_unknown_pipeline_status_fails_closed(self):
        real_prepare = integration.prepare_batch

        def altered(*args, **kwargs):
            batch = real_prepare(*args, **kwargs)
            report = deepcopy(batch.report)
            report["items"][0]["statuses"] = ["unknown-new-state"]
            return replace(batch, report=report)

        with patch.object(integration, "prepare_batch", side_effect=altered):
            with self.assertRaises(ValueError):
                integration.build_preview_rows()

    def test_blocked_row_with_reference_does_not_hide_other_rows(self):
        fixtures = deepcopy(integration._SYNTHETIC_ROWS)
        fixtures[0]["unapproved_extra_field"] = True
        with patch.object(integration, "_SYNTHETIC_ROWS", fixtures):
            try:
                rows = integration.build_preview_rows()
            except ValueError:
                self.fail("One blocked row must not make the whole valid batch unavailable")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].status, "blocked-invalid")
        self.assertFalse(rows[0].draft_created)
        self.assertTrue(all(ref.citation is None for ref in rows[0].references))
        self.assertIn("رابط المقطع الجاهز", rows[0].media_status)
        self.assertIn("invalid_input", getattr(rows[0], "issue_codes", ()))

    def test_review_reasons_are_specific_and_keep_original_text(self):
        rows = integration.build_preview_rows()
        self.assertEqual(getattr(rows[0], "issue_codes", ()), ())
        self.assertIn("reference_unverified", getattr(rows[1], "issue_codes", ()))
        self.assertIn("media_missing", getattr(rows[2], "issue_codes", ()))
        self.assertIn("references_missing", getattr(rows[2], "issue_codes", ()))
        self.assertIn("media_invalid", getattr(rows[3], "issue_codes", ()))
        self.assertEqual(rows[0].question, integration._SYNTHETIC_ROWS[0]["question"])

    def test_citation_text_is_escaped_once_at_html_boundary(self):
        real_dependencies = integration._synthetic_dependencies
        label = "باب <اختبار> & توثيق"

        def altered():
            mapping, bridge, catalog = real_dependencies()
            evidence = replace(catalog.lookup(41, 73)[0], heading_title=label, path=("كتاب الطهارة", label))
            return mapping, bridge, SnapshotCatalog((evidence,))

        with patch.object(integration, "_synthetic_dependencies", side_effect=altered):
            rows = integration.build_preview_rows()
            self.assertIn(label, rows[0].references[0].citation or "")
            response = self.get("/SYN-P01")
        self.assertContains(response, "باب &lt;اختبار&gt; &amp; توثيق")
        self.assertNotContains(response, "&amp;lt;")
        self.assertNotContains(response, "<اختبار>")

    def test_summary_counts_entire_batch_and_filtered_count_separately(self):
        response = self.get()
        expected = {"total": 4, "ready": 1, "needs_review": 2, "blocked": 1, "drafts": 2,
                    "verified_references": 1, "unverified_references": 1}
        self.assertEqual(response.context.get("summary"), expected)
        self.assertEqual(response.context.get("matched_count"), 4)
        self.assertContains(response, 'aria-label="ملخص الدفعة"')
        response = self.get("?status=needs-editor-review")
        self.assertEqual(response.context.get("summary"), expected)
        self.assertEqual(response.context.get("matched_count"), 2)

    def test_filter_by_missing_media_reason(self):
        response = self.get("?issue=media_missing")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SYN-P03")
        self.assertNotContains(response, "SYN-P01")
        self.assertNotContains(response, "SYN-P02")
        self.assertNotContains(response, "SYN-P04")
        self.assertEqual(response.context.get("matched_count"), 1)

    def test_pagination_and_detail_return_keep_filter_state(self):
        response = self.get("?q=سؤال&page_size=2")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SYN-P01")
        self.assertNotContains(response, "SYN-P03")
        next_url = response.context.get("next_url")
        self.assertIsNotNone(next_url)
        params = parse_qs(urlsplit(next_url).query)
        self.assertEqual(params["q"], ["سؤال"])
        self.assertEqual(params["page"], ["2"])
        self.assertEqual(params["page_size"], ["2"])
        second = self.client.get(next_url, HTTP_HOST="localhost")
        self.assertContains(second, "SYN-P03")
        self.assertContains(second, "SYN-P04")
        self.assertNotContains(second, "SYN-P01")
        detail = self.get("/SYN-P03?q=سؤال&page_size=2&page=2")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(parse_qs(detail.context["filter_query"])["page"], ["2"])
        self.assertEqual(parse_qs(detail.context["filter_query"])["q"], ["سؤال"])

    def test_invalid_page_and_issue_fail_before_processing(self):
        with patch("apps.editorial_demo.views.build_preview_rows", side_effect=AssertionError("unexpected processing")):
            for suffix in ("?page=0", "?page=-1", "?page=01", "?page=٢", "?page=10001",
                           "?page_size=0", "?page_size=51", "?page_size=x", "?issue=private",
                           "?page=1&page=2", "?issue=media_missing&issue=media_invalid"):
                response = self.get(suffix)
                self.assertEqual(response.status_code, 400, suffix)
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_empty_first_page_and_out_of_range(self):
        self.assertEqual(self.get("?q=nomatch&page=1").status_code, 200)
        self.assertEqual(self.get("?page_size=2&page=3").status_code, 404)
        self.assertEqual(self.get("?q=nomatch&page=2").status_code, 404)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=3)
    def test_excessive_query_fields_are_safe_no_store_response(self):
        response = self.get("?q=a&q=b&q=c&q=d")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get("Cache-Control"), "no-store")

    def test_navigation_from_previous_preview_reaches_connected_worklist(self):
        response = self.client.get("/dev/editorial-preview", HTTP_HOST="localhost")
        self.assertContains(response, 'href="/dev/editorial-preview/pipeline"')

    def test_filtering_does_not_mutate_batch_or_create_state(self):
        before = integration.build_preview_rows()
        self.get("?issue=media_missing&page_size=2")
        self.get("/SYN-P01")
        self.assertEqual(before, integration.build_preview_rows())
