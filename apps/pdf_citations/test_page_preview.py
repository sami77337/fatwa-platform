"""Synthetic single-page derivative verification; no Django, file or user data."""

import io
import json
import subprocess
import unittest
from hashlib import sha256
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from .page_preview import PdfPageUnavailable, selected_page


def multipage_pdf():
    writer = PdfWriter()
    for width in (300, 400, 500):
        writer.add_blank_page(width=width, height=600)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class SelectedPageDerivativeTests(unittest.TestCase):
    def setUp(self):
        self.raw = multipage_pdf()

    def test_only_the_exact_requested_physical_page_is_exported(self):
        original_sha = sha256(self.raw).hexdigest()
        for number, width in ((1, 300), (2, 400), (3, 500)):
            with self.subTest(page=number):
                chosen = selected_page(self.raw, page_number=number, page_count=3)
                reader = PdfReader(io.BytesIO(chosen), strict=True)
                self.assertEqual(len(reader.pages), 1)
                self.assertEqual(float(reader.pages[0].mediabox.width), width)
                self.assertNotEqual(chosen, self.raw)
        self.assertEqual(sha256(self.raw).hexdigest(), original_sha)
        self.assertEqual(len(PdfReader(io.BytesIO(self.raw)).pages), 3)

    def test_wrong_page_and_boolean_coercion_fail_before_subprocess(self):
        for page, pages in ((0, 3), (4, 3), (2, 2), (True, 3), (2, False), (2, 11)):
            with self.subTest(page=page, pages=pages), self.assertRaises(PdfPageUnavailable):
                selected_page(self.raw, page_number=page, page_count=pages)
        with self.assertRaises(PdfPageUnavailable):
            selected_page(bytearray(self.raw), page_number=2, page_count=3)

    def test_malformed_or_active_pdf_is_rejected(self):
        for raw in (b"%PDF-not-a-real-file\n%%EOF", self.raw[:-5] + b"broken"):
            with self.subTest(raw=raw[:20]), self.assertRaises(PdfPageUnavailable):
                selected_page(raw, page_number=2, page_count=3)
        writer = PdfWriter()
        writer.add_blank_page(width=400, height=600)
        writer.add_js("this.print();")
        output = io.BytesIO()
        writer.write(output)
        with self.assertRaises(PdfPageUnavailable):
            selected_page(output.getvalue(), page_number=1, page_count=1)

    def test_worker_failure_timeout_or_forged_response_stays_closed(self):
        bad = (
            subprocess.CompletedProcess([], 1, stdout=""),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({"page_number": 2, "page_count": 3, "pdf": ""})),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({"page_number": 1, "page_count": 1, "pdf": ""})),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({"page_number": 2, "page_count": 1, "pdf": "YWJj"})),
        )
        for response in bad:
            with patch("apps.pdf_citations.page_preview.subprocess.run", return_value=response):
                with self.assertRaises(PdfPageUnavailable):
                    selected_page(self.raw, page_number=2, page_count=3)

        with patch(
            "apps.pdf_citations.page_preview.subprocess.run",
            side_effect=subprocess.TimeoutExpired("page_worker", 6),
        ):
            with self.assertRaises(PdfPageUnavailable):
                selected_page(self.raw, page_number=2, page_count=3)


if __name__ == "__main__":
    unittest.main()
