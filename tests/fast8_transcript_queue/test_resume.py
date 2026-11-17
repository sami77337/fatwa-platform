"""Portable resume preserves source lineage without trusting archive metadata."""

import io
import json
import unittest
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile

from django.test import SimpleTestCase, override_settings

from apps.fast8_transcript_queue.workbench import services as s
from tests.fast8_transcript_queue import test_workbench_http as web
from tests.fast8_transcript_queue.test_services import encode, segments


def edited_document(*, overlap=False, suffix=".json"):
    rows = segments()
    if overlap:
        rows[1]["start_ms"] = 1000
    document = s.open_document(encode(rows, suffix), suffix, synthetic_fixtures_only=True)
    return s.revise(
        document, index=0, start_ms=18, end_ms=1017, replacement_text="  تعديل اصطناعي\r\nمحفوظ  "
    )


class ResumeServicesTests(unittest.TestCase):
    def test_resume_complete_bundle_retains_original_edits_and_deterministic_exports(self):
        for suffix in (".csv", ".jsonl", ".json"):
            with self.subTest(suffix=suffix):
                document = edited_document(suffix=suffix)
                raw = s.export_bundle(document)
                restored = s.restore_bundle(raw, synthetic_fixtures_only=True)
                self.assertEqual(restored, document)
                self.assertEqual(s.export_bundle(restored), raw)
                continued = s.revise(restored, index=1, start_ms=1018, end_ms=2019)
                self.assertEqual(continued.original, document.original)
                self.assertEqual(continued.revision, 2)

    def test_checkpoint_can_resume_unresolved_overlap_but_never_prepare_questions(self):
        document = edited_document(overlap=True)
        raw = s.checkpoint(document)
        with ZipFile(io.BytesIO(raw)) as archive:
            self.assertCountEqual(
                archive.namelist(), ["original.json", "reviewed.json", "manifest.json"]
            )
        restored = s.restore_bundle(raw, synthetic_fixtures_only=True)
        self.assertEqual(restored, document)
        with self.assertRaises(s.ValidationError):
            s.export_bundle(restored)
        fixed = s.revise(restored, index=1, start_ms=1017, end_ms=2019)
        self.assertEqual(
            s.restore_bundle(s.export_bundle(fixed), synthetic_fixtures_only=True), fixed
        )

    def test_rejects_forged_derived_content_even_if_attacker_rehashes_manifest(self):
        files = s._read_archive(s.export_bundle(edited_document()))
        for filename in ("queue.json", "prepared-questions.json", "timeline.json", "cues.json"):
            with self.subTest(filename=filename):
                changed = dict(files)
                changed[filename] = b'{"approval_granted":true}\n'
                manifest = json.loads(changed["manifest.json"])
                for entry in manifest["files"]:
                    if entry["name"] == filename:
                        entry.update(
                            bytes=len(changed[filename]),
                            sha256=sha256(changed[filename]).hexdigest(),
                        )
                changed["manifest.json"] = s.pipeline._encoded(manifest)
                with self.assertRaises(s.ValidationError):
                    s.restore_bundle(s._archive(changed), synthetic_fixtures_only=True)

    def test_rejects_wrong_source_identity_non_synthetic_and_manifest_authority(self):
        files = s._read_archive(s.checkpoint(edited_document()))
        mutations = (
            ("manifest.json", lambda value: value.update(approval_granted=True)),
            ("manifest.json", lambda value: value.update(revision=True)),
            ("manifest.json", lambda value: value.update(case_binding="AUTHORIZED")),
            ("reviewed.json", lambda value: value["items"][0].update(source_id="another-source")),
            ("original.json", lambda value: value[0].update(fabricated=False)),
        )
        for filename, mutate in mutations:
            with self.subTest(filename=filename):
                changed = dict(files)
                value = json.loads(changed[filename])
                mutate(value)
                changed[filename] = s.pipeline._encoded(value)
                with self.assertRaises(s.ValidationError):
                    s.restore_bundle(s._archive(changed), synthetic_fixtures_only=True)

    def test_archive_limits_unknown_duplicate_traversal_and_compression_are_rejected(self):
        raw = s.checkpoint(edited_document())
        with self.assertRaises(s.ValidationError):
            s.restore_bundle(raw)
        for payload in (b"not-zip", b"x" * (s.MAX_BUNDLE_BYTES + 1), raw[:-20]):
            with self.assertRaises(s.ValidationError):
                s.restore_bundle(payload, synthetic_fixtures_only=True)
        files = s._read_archive(raw)
        for filename in ("../escape.json", "/original.json", "extra.json"):
            with self.subTest(filename=filename), self.assertRaises(s.ValidationError):
                s.restore_bundle(
                    s._archive({**files, filename: b"x"}), synthetic_fixtures_only=True
                )
        for compression, duplicate in ((ZIP_DEFLATED, False), (0, True)):
            stream = io.BytesIO()
            with ZipFile(stream, "w", compression=compression) as archive:
                for filename, content in files.items():
                    archive.writestr(filename, content)
                if duplicate:
                    import warnings

                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        archive.writestr("manifest.json", files["manifest.json"])
            with self.assertRaises(s.ValidationError):
                s.restore_bundle(stream.getvalue(), synthetic_fixtures_only=True)


@override_settings(FATWA_TRANSCRIPT_WORKBENCH_ENABLED=True, SECRET_KEY="synthetic-test-secret")
class ResumeHTTPTests(SimpleTestCase):
    setUp = web.WorkbenchHTTPTests.setUp
    browser = web.WorkbenchHTTPTests.browser
    upload = web.WorkbenchHTTPTests.upload
    submit = web.WorkbenchHTTPTests.submit

    def test_resume_after_new_browser_and_new_signing_key_keeps_comparison_and_original(self):
        page = self.upload()
        page = self.submit(
            page,
            "revise",
            index=0,
            start_ms=18,
            end_ms=1017,
            text="<نص اصطناعي مراجع>",
            replace_text="yes",
        )
        self.assertContains(page, "مقارنة المقطع بالأصل المحفوظ")
        checkpoint = self.submit(page, "checkpoint")
        self.assertEqual(checkpoint.status_code, 200)
        self.assertIn("checkpoint.zip", checkpoint["Content-Disposition"])
        self.client = self.browser()
        with override_settings(SECRET_KEY="new-synthetic-key-after-restart"):
            restored = self.upload(filename="checkpoint.zip", raw=checkpoint.content)
            self.assertContains(restored, "مقارنة المقطع بالأصل المحفوظ")
            self.assertContains(restored, "&lt;نص اصطناعي مراجع&gt;")
            exported = self.submit(restored, "export")
        with ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertEqual(archive.read("original.json"), encode(segments()))
            self.assertEqual(json.loads(archive.read("reviewed.json"))["items"][0]["start_ms"], 18)

    def test_browser_resume_unfinished_review_retains_export_block_until_repair(self):
        rows = segments()
        rows[1]["start_ms"] = 1000
        page = self.upload(rows)
        checkpoint = self.submit(page, "checkpoint")
        page = self.upload(filename="checkpoint.zip", raw=checkpoint.content)
        self.assertContains(page, "تداخل بين مقطعين")
        self.assertEqual(self.submit(page, "export").status_code, 400)
        page = self.submit(page, "revise", index=1, start_ms=1017, end_ms=2019, text="")
        self.assertEqual(self.submit(page, "export").status_code, 200)

    def test_import_tampered_archive_rejects_without_rendering_untrusted_contents(self):
        self.assertEqual(self.upload(filename="bad.zip", raw=b"invalid").status_code, 400)
        files = s._read_archive(s.checkpoint(edited_document()))
        files["reviewed.json"] = b"secret-rejected-payload"
        page = self.upload(filename="bad.zip", raw=s._archive(files))
        self.assertEqual(page.status_code, 400)
        self.assertNotIn(b"secret-rejected-payload", page.content)
