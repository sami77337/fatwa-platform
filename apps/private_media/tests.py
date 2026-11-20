"""Parser admission tests use tiny fabricated files, never production documents."""

import io
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .fixtures import synthetic_files
from .storage import InlineDatabaseStorage, StoredOriginal, configured_storage
from .validation import MediaValidationError, validate


class ValidationTests(SimpleTestCase):
    def test_every_supported_type_is_parsed_and_original_is_unchanged(self):
        for filename, media_type, raw in synthetic_files():
            with self.subTest(filename=filename):
                result = validate(raw, filename, media_type)
                self.assertEqual(result.raw, raw)
                self.assertEqual(result.sha256, sha256(raw).hexdigest())
                self.assertEqual(result.size, len(raw))
                self.assertTrue(result.metadata["validated"])
                store = InlineDatabaseStorage()
                self.assertEqual(store.get(store.put(result)), raw)

    def test_extension_mime_signature_truncation_and_size_fail_closed(self):
        for filename, media_type, raw in synthetic_files():
            for bad_raw, bad_name, bad_type in (
                (b"not a media file", filename, media_type),
                (raw[:8], filename, media_type),
                (raw, "../" + filename, media_type),
                (raw, filename, "application/octet-stream"),
            ):
                if media_type == "text/plain" and bad_type == media_type and bad_name == filename:
                    continue
                with self.subTest(filename=filename), self.assertRaises(MediaValidationError):
                    validate(bad_raw, bad_name, bad_type)
        with self.assertRaises(MediaValidationError):
            validate(b"x" * 192001, "huge.pdf", "application/pdf")
        with self.assertRaises(MediaValidationError):
            validate(b"x" * 65537, "huge.txt", "text/plain")

    def test_pdf_active_content_encryption_and_page_limits_rejected(self):
        from pypdf import PdfWriter

        for mode in ("script", "encrypted", "pages", "link"):
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            if mode == "script":
                from pypdf.generic import DictionaryObject, NameObject, TextStringObject

                writer.root_object[NameObject("/OpenAction")] = DictionaryObject(
                    {
                        NameObject("/S"): NameObject("/JavaScript"),
                        NameObject("/JS"): TextStringObject("app.alert('synthetic')"),
                    }
                )
            elif mode == "encrypted":
                writer.encrypt("synthetic")
            elif mode == "link":
                from pypdf.annotations import Link

                writer.add_annotation(0, Link(rect=(0, 0, 10, 10), url="https://example.invalid/"))
            else:
                for _ in range(10):
                    writer.add_blank_page(width=200, height=200)
            output = io.BytesIO()
            writer.write(output)
            with self.subTest(mode=mode), self.assertRaises(MediaValidationError):
                validate(output.getvalue(), "source.pdf", "application/pdf")

    def test_large_image_and_animated_webp_rejected(self):
        from PIL import Image

        output = io.BytesIO()
        Image.new("RGB", (2500, 2000)).save(output, format="PNG")
        with self.assertRaises(MediaValidationError):
            validate(output.getvalue(), "large.png", "image/png")
        output = io.BytesIO()
        Image.new("RGB", (16, 16), "red").save(
            output,
            format="WEBP",
            save_all=True,
            append_images=[Image.new("RGB", (16, 16), "blue")],
            duration=100,
            loop=0,
        )
        with self.assertRaises(MediaValidationError):
            validate(output.getvalue(), "animated.webp", "image/webp")

    def test_m4a_external_data_reference_is_rejected(self):
        filename, media_type, raw = next(
            item for item in synthetic_files() if item[0].endswith(".m4a")
        )
        position = raw.index(b"url ") + 4
        self.assertEqual(raw[position : position + 4], b"\x00\x00\x00\x01")
        external = raw[:position] + b"\x00\x00\x00\x00" + raw[position + 4 :]
        with self.assertRaises(MediaValidationError):
            validate(external, filename, media_type)

    def test_storage_corruption_configuration_and_parser_failure_rejected(self):
        media = validate(b"synthetic", "source.txt", "text/plain")
        store = InlineDatabaseStorage()
        stored = store.put(media)
        with self.assertRaises(MediaValidationError):
            store.get(replace(stored, inline=b"changed"))
        with self.assertRaises(MediaValidationError):
            store.get(
                StoredOriginal("public-url", "https://example.invalid", stored.sha256, stored.size)
            )
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE="https://example.invalid"):
            with self.assertRaises(MediaValidationError):
                configured_storage()
        with patch("apps.private_media.validation.subprocess.run", side_effect=OSError):
            with self.assertRaises(MediaValidationError):
                validate(b"synthetic", "source.txt", "text/plain")

    def test_parser_worker_receives_only_minimal_environment_and_fixed_cwd(self):
        import json
        import os
        from pathlib import Path
        from subprocess import CompletedProcess

        expected = {"validated": True, "encoding": "UTF-8"}
        with patch(
            "apps.private_media.validation.subprocess.run",
            return_value=CompletedProcess([], 0, stdout=json.dumps(expected)),
        ) as run:
            validate(b"synthetic", "source.txt", "text/plain")
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["env"], {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        })
        self.assertEqual(kwargs["cwd"], Path(__file__).resolve().parents[2])
        self.assertNotIn("DATABASE_URL", kwargs["env"])
        self.assertNotIn("SECRET_KEY", kwargs["env"])
        self.assertNotIn("PYTHONPATH", kwargs["env"])

    def test_pdf_worker_requires_all_resource_limits(self):
        from types import SimpleNamespace
        from .worker import _apply_pdf_resource_limits

        calls = []
        fake = SimpleNamespace(
            RLIMIT_CPU=1, RLIMIT_AS=2, RLIMIT_FSIZE=3, RLIMIT_NOFILE=4, RLIMIT_CORE=5,
            setrlimit=lambda kind, value: calls.append((kind, value)),
        )
        with patch.dict("sys.modules", {"resource": fake}):
            _apply_pdf_resource_limits()
        self.assertEqual(calls, [
            (1, (3, 3)), (2, (268435456, 268435456)),
            (3, (1048576, 1048576)), (4, (32, 32)), (5, (0, 0)),
        ])

    def test_pdf_worker_fails_closed_when_resource_limits_are_unavailable(self):
        import builtins
        from .worker import _apply_pdf_resource_limits

        original = builtins.__import__
        def no_resource(name, *args, **kwargs):
            if name == "resource":
                raise ImportError("unavailable")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=no_resource):
            with self.assertRaises(ImportError):
                _apply_pdf_resource_limits()
