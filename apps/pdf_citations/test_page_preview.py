"""Synthetic single-page derivative verification; no Django, file or user data."""

import base64
import io
import os
import json
import subprocess
import unittest
import io
from pathlib import Path
from hashlib import sha256
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.actions import JavaScript

from .page_preview import PdfPageUnavailable, selected_page
from .page_worker import apply_resource_limits, produce


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

    def test_worker_requires_all_os_resource_limits(self):
        from types import SimpleNamespace

        calls = []
        fake = SimpleNamespace(
            RLIMIT_CPU=1,
            RLIMIT_AS=2,
            RLIMIT_FSIZE=3,
            RLIMIT_NOFILE=4,
            RLIMIT_CORE=5,
            setrlimit=lambda kind, value: calls.append((kind, value)),
        )
        with patch.dict("sys.modules", {"resource": fake}):
            apply_resource_limits()
        self.assertEqual(
            calls,
            [(1, (3, 3)), (2, (268435456, 268435456)), (3, (1048576, 1048576)),
             (4, (32, 32)), (5, (0, 0))],
        )

    def test_missing_os_resource_limits_are_not_silently_ignored(self):
        import builtins

        original = builtins.__import__

        def no_resource(name, *args, **kwargs):
            if name == "resource":
                raise ImportError("unavailable")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=no_resource):
            with self.assertRaises(ImportError):
                apply_resource_limits()

    def test_worker_invocation_uses_sanitized_environment_and_fixed_cwd(self):
        selected = produce(self.raw, 2, 3)
        response = json.dumps(
            {"page_number": 2, "page_count": 1, "pdf": base64.b64encode(selected).decode("ascii")}
        ).encode("utf-8")
        class FakeProcess:
            def __init__(self, *args, **kwargs):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(response)
            def wait(self, timeout=None):
                return 0
            def kill(self):
                return None
        with patch(
            "apps.pdf_citations.page_preview.subprocess.Popen", side_effect=FakeProcess
        ) as run:
            self.assertEqual(selected_page(self.raw, page_number=2, page_count=3), selected)
        kwargs = run.call_args.kwargs
        self.assertEqual(
            kwargs["env"],
            {
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
            },
        )
        self.assertEqual(kwargs["cwd"], Path(__file__).resolve().parents[2])
        self.assertNotIn("DATABASE_URL", kwargs["env"])
        self.assertNotIn("SECRET_KEY", kwargs["env"])
        self.assertNotIn("PYTHONPATH", kwargs["env"])

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
        writer.add_open_action(JavaScript("this.print();"))
        output = io.BytesIO()
        writer.write(output)
        with self.assertRaises(PdfPageUnavailable):
            selected_page(output.getvalue(), page_number=1, page_count=1)

    def test_worker_failure_timeout_or_forged_response_stays_closed(self):
        bad = (
            (1, b""),
            (0, json.dumps({"page_number": 2, "page_count": 3, "pdf": ""}).encode()),
            (0, json.dumps({"page_number": 1, "page_count": 1, "pdf": ""}).encode()),
            (0, json.dumps({"page_number": 2, "page_count": 1, "pdf": "YWJj"}).encode()),
        )
        for code, response in bad:
            class FakeProcess:
                def __init__(self, *args, **kwargs):
                    self.stdin = io.BytesIO()
                    self.stdout = io.BytesIO(response)
                def wait(self, timeout=None):
                    return code
                def kill(self):
                    return None
            with patch("apps.pdf_citations.page_preview.subprocess.Popen", side_effect=FakeProcess):
                with self.assertRaises(PdfPageUnavailable):
                    selected_page(self.raw, page_number=2, page_count=3)

        class OversizedProcess:
            def __init__(self, *args, **kwargs):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(b"x" * 400001)
            def wait(self, timeout=None):
                return 0
            def kill(self):
                return None
        with patch("apps.pdf_citations.page_preview.subprocess.Popen", side_effect=OversizedProcess):
            with self.assertRaises(PdfPageUnavailable):
                selected_page(self.raw, page_number=2, page_count=3)

        with patch(
            "apps.pdf_citations.page_preview.subprocess.Popen",
            side_effect=subprocess.TimeoutExpired("page_worker", 6),
        ):
            with self.assertRaises(PdfPageUnavailable):
                selected_page(self.raw, page_number=2, page_count=3)


if __name__ == "__main__":
    unittest.main()
