"""Pure presentation tests using fabricated inputs, never owner source archives."""

import hashlib
import json
import unittest
from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch

from apps.intake_workflow import contracts as c
from apps.reference_links.diagnostics import build_reference_diagnostics
from apps.reference_links.resolution import Heading


ROOT = Heading(
    7001, 1, "مرجع اصطناعي لتجارب Wave7", "كِتَابٌ اصطناعي", "الأول", 7,
    ("كِتَابٌ اصطناعي",), c.SOURCE_IDENTITY["source_namespace"], "622",
    c.SOURCE_IDENTITY["source_input_sha256"], c.SOURCE_IDENTITY["edition_key"],
    c.SOURCE_IDENTITY["source_archive_sha256"],
)
POINTER = {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"}


def report_for(items, rows=(ROOT,)):
    raw = json.dumps({"schema": c.PAYLOAD_SCHEMA, "synthetic_fixtures_only": True,
                      "items": items}, ensure_ascii=False, indent=2).encode("utf-8")
    return raw, build_reference_diagnostics(
        raw, synthetic_fixtures_only=True, catalog_rows=rows,
    )


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.pre = []
        self.current_pre = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "pre":
            self.current_pre = []

    def handle_endtag(self, tag):
        if tag == "pre":
            self.pre.append("".join(self.current_pre))
            self.current_pre = None

    def handle_data(self, data):
        self.text.append(data)
        if self.current_pre is not None:
            self.current_pre.append(data)


class DiagnosticPresentationTests(unittest.TestCase):
    def setUp(self):
        from apps.reference_links import diagnostic_presentation as presentation

        self.p = presentation

    def html(self, report, **kwargs):
        return self.p.render_reference_diagnostics_html(
            report, synthetic_fixtures_only=True, **kwargs,
        )

    def text(self, report, **kwargs):
        return self.p.render_reference_diagnostics_text(
            report, synthetic_fixtures_only=True, **kwargs,
        )

    def test_arabic_semantic_report_exposes_statuses_and_exact_evidence(self):
        raw, report = report_for([{"reference_links": [
            POINTER, {"source_id": "missing", "heading_id": "missing"},
            {**c.SOURCE_IDENTITY, "source_id": "wrong"},
        ]}])
        html = self.html(report)
        doc = Document(html)
        self.assertIn(("html", {"lang": "ar", "dir": "rtl"}), doc.tags)
        self.assertEqual(sum(tag == "h1" for tag, _ in doc.tags), 1)
        self.assertTrue(any(tag == "caption" for tag, _ in doc.tags))
        self.assertTrue(any(tag == "th" and attrs.get("scope") == "col"
                            for tag, attrs in doc.tags))
        self.assertIn("VERIFIED", "".join(doc.text))
        self.assertIn("UNVERIFIED", "".join(doc.text))
        self.assertIn("MISMATCHED", "".join(doc.text))
        self.assertIn("تطابق تقني", "".join(doc.text))
        self.assertIn(hashlib.sha256(raw).hexdigest(), html)
        for item in report.items:
            self.assertIn(item.source.text, doc.pre)
            for ref in item.references:
                self.assertIn(ref.source.text, doc.pre)
                self.assertIn(hashlib.sha256(raw[ref.source.start:ref.source.end]).hexdigest(), html)
        self.assertTrue(any('"source_row_id": 1' in block for block in doc.pre))
        self.assertTrue(any('"source_archive_sha256": "' + "a" * 64 in block
                            for block in doc.pre))

    def test_hostile_source_catalog_and_reasons_are_inert_exact_text(self):
        hostile = '</pre><script>alert("x")</script><a href="javascript:x">\' & سُؤال 🧪\n\t'
        _, report = report_for([{"question": hostile,
                                "url": "https://example.invalid/a?x=1&y=2",
                                "reference_links": [{"source_id": hostile}]}],
                              (replace(ROOT, heading_title=hostile, path=(hostile,)),))
        ref = report.items[0].references[0]
        reason = '<img src=x onerror="x">'
        changed = replace(report, items=(replace(report.items[0], references=(
            replace(ref, reasons=(reason,)),)),))
        html = self.html(changed)
        doc = Document(html)
        forbidden = {"a", "script", "style", "img", "form", "input", "iframe", "link"}
        self.assertFalse(any(tag in forbidden for tag, _ in doc.tags))
        self.assertFalse(any(name.startswith("on") or name in {"href", "src"}
                             for _, attrs in doc.tags for name in attrs))
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&quot;x&quot;", html)
        self.assertIn("&#x27;", html)
        self.assertIn(reason, "".join(doc.text))
        self.assertIn(changed.items[0].source.text, doc.pre)
        self.assertIn(hostile, "".join(json.loads(block)["path"][0]
                                      for block in doc.pre if block.startswith('{\n  "edition_id"')))
        self.assertIn(changed.items[0].source.text, self.text(changed))

    def test_reason_order_and_untranslated_codes_are_preserved(self):
        _, report = report_for([{"reference_links": [POINTER]}])
        ref = replace(report.items[0].references[0], reasons=(
            "multiple_exact_candidates", "future_reason", "identity_not_found",
        ))
        report = replace(report, items=(replace(report.items[0], references=(ref,)),))
        for output in (self.html(report), self.text(report)):
            self.assertLess(output.index("multiple_exact_candidates"), output.index("future_reason"))
            self.assertLess(output.index("future_reason"), output.index("identity_not_found"))
            self.assertIn("سبب تشخيصي غير مترجم", output)

    def test_empty_input_items_and_missing_reference_evidence_are_explicit(self):
        for items in ([], [{"question": "بلا إحالات"}], [{"reference_links": [POINTER]}]):
            with self.subTest(items=items):
                # The intake builder requires a nonempty envelope. The renderer
                # also handles an explicitly constructed empty report value.
                _, report = report_for(items or [{}], ())
                if not items:
                    report = replace(report, items=())
                for output in (self.html(report), self.text(report)):
                    self.assertIn("لا توجد", output)
                    self.assertNotIn("إحالة معتمدة", output)
                if report.items and report.items[0].references:
                    self.assertIn("لا يوجد دليل مطابق", self.html(report))
                    self.assertIn("identity_not_found", self.html(report))

    def test_limits_never_claim_archive_or_scholarly_verification(self):
        _, report = report_for([{"reference_links": [POINTER]}])
        for output in (self.html(report), self.text(report)):
            for token in ("NOT_PASSED", "HOLD", "BLOCKED", "SCOPE_DEVIATION_HOLD",
                          "NOT_DEPLOYED/GATES_HOLD", "SOURCE_BOOK_TOC_NOT_FATWAS",
                          "لا تعني فحص الأرشيف", "لا تثبت", "اصطناعي"):
                self.assertIn(token, output)

    def test_same_report_is_deterministic_and_does_not_mutate_objects_or_raw_bytes(self):
        raw, report = report_for([{"reference_links": [POINTER]}])
        before = report.json_bytes()
        raw_before = bytes(raw)
        for render in (self.html, self.text):
            first = render(report)
            self.assertEqual(first, render(report))
            self.assertTrue(first.endswith("\n"))
        self.assertEqual(before, report.json_bytes())
        self.assertEqual(raw_before, raw)

    def test_html_pre_preserves_unicode_whitespace_and_exact_number_tokens(self):
        raw = ('{"schema":"' + c.PAYLOAD_SCHEMA + '","synthetic_fixtures_only":true,'
               '"items":[ {\n\t"سُؤال": "نص 🧪", "reference_links": [\n'
               '  1e-20000, 73.000000000000001, null\n ]\n} ]}').encode()
        report = build_reference_diagnostics(raw, synthetic_fixtures_only=True)
        doc = Document(self.html(report))
        self.assertIn(report.items[0].source.text, doc.pre)
        self.assertIn("1e-20000", doc.pre)
        self.assertIn("73.000000000000001", doc.pre)
        self.assertIn("null", doc.pre)
        text = "".join(doc.text)
        for ordinal in (1, 2, 3):
            self.assertIn(f"العنصر 1 — الإحالة {ordinal}", text)

    def test_output_budget_counts_utf8_bytes_and_rejects_without_truncation(self):
        _, report = report_for([{"question": "عربي 🧪", "reference_links": [POINTER]}])
        for render in (self.html, self.text):
            complete = render(report)
            size = len(complete.encode("utf-8"))
            self.assertGreater(size, len(complete))
            self.assertEqual(complete, render(report, max_output_bytes=size))
            with self.assertRaisesRegex(self.p.DiagnosticPresentationError, "output_limit_exceeded"):
                render(report, max_output_bytes=size - 1)
        for budget in (True, 0, -1, 1.5, "100", self.p.MAX_OUTPUT_BYTES + 1):
            with self.subTest(budget=budget), self.assertRaisesRegex(
                self.p.DiagnosticPresentationError, "invalid_output_limit",
            ):
                self.html(report, max_output_bytes=budget)

    def test_html_encodes_carriage_returns_before_browser_newline_normalization(self):
        raw, _ = report_for([{"question": "سطر عربي", "reference_links": [POINTER]}])
        raw = raw.replace(b"\n", b"\r\n")
        report = build_reference_diagnostics(raw, synthetic_fixtures_only=True, catalog_rows=(ROOT,))
        html = self.html(report)
        self.assertIn("&#13;", html)
        self.assertNotIn("\r", html)
        self.assertIn(report.items[0].source.text, Document(html).pre)
        self.assertIn(report.items[0].source.text, self.text(report))

    def test_literal_acknowledgement_and_report_type_are_required(self):
        _, report = report_for([{}])
        for render in (self.p.render_reference_diagnostics_html,
                       self.p.render_reference_diagnostics_text):
            for ack in (False, None, 1, "true"):
                with self.subTest(ack=ack), self.assertRaisesRegex(
                    self.p.DiagnosticPresentationError, "synthetic_acknowledgement_required",
                ):
                    render(report, synthetic_fixtures_only=ack)
            with self.assertRaisesRegex(self.p.DiagnosticPresentationError, "diagnostic_report_required"):
                render(report.to_payload(), synthetic_fixtures_only=True)

    def test_rendering_does_not_open_files_network_database_or_resolve_again(self):
        from django.db.backends.base.base import BaseDatabaseWrapper

        _, report = report_for([{"reference_links": [POINTER]}])
        with patch("builtins.open", side_effect=AssertionError("file I/O")), \
             patch("socket.socket", side_effect=AssertionError("network I/O")), \
             patch.object(BaseDatabaseWrapper, "connect", side_effect=AssertionError("DB connect")), \
             patch.object(BaseDatabaseWrapper, "cursor", side_effect=AssertionError("DB query")), \
             patch("apps.reference_links.diagnostics.plan_reference_verification",
                   side_effect=AssertionError("second resolution")):
            self.assertIn("VERIFIED", self.html(report))
            self.assertIn("VERIFIED", self.text(report))
