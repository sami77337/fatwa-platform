"""Current tool grants cannot extend publication scope or survive late callbacks."""

import uuid
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationAction
from apps.library_preview import services as preview
from apps.public_answer_media.boundaries import core_state

from . import services, views
from .test_support import FEATURES, FixtureAuthority, ReaderFixture


@override_settings(**FEATURES)
class ReaderToolsTests(ReaderFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.url = f"/library-preview/reading/{self.publication.pk}/"

    def test_native_connected_entry_and_exact_reference_descriptors(self):
        detail = self.client.get(f"/library-preview/editions/{self.publication.pk}/")
        self.assertContains(detail, "حفظ ومشاركة وطباعة الجواب")
        response = self.client.get(self.url)
        self.assertContains(response, self.publication.body)
        self.assertContains(response, "على هذا الجهاز فقط")
        self.assertContains(response, "لا يحفظ الجواب أو مرفقاته دون اتصال")
        self.assertNotContains(response, "PRIVATE")
        self.assertNotContains(response, self.receipt["public_ref"])
        self.assertNotContains(response, str(self.part.pk))
        for path in ("save-reference/", "share-link/", "print-permission/"):
            with self.subTest(path=path):
                row = self.client.get(self.url + path).json()
                self.assertEqual(
                    set(row),
                    {
                        "publication_id",
                        "version",
                        "content_sha256",
                        "title",
                        "url",
                        "reader_url",
                    },
                )
                self.assertEqual(row["publication_id"], str(self.publication.pk))
                self.assertEqual(row["content_sha256"], self.publication.content_sha256)
                self.assertEqual(row["url"], f"/library-preview/editions/{self.publication.pk}/")
                self.assertNotIn("body", row)

    def test_four_capabilities_are_independent_and_read_does_not_grant_them(self):
        routes = {
            "SAVE_REFERENCE": ("save-reference/", "حفظ المرجع على هذا الجهاز"),
            "SHARE_LINK": ("share-link/", "نسخ رابط النسخة العامة"),
            "PRINT": ("print/", "فتح نسخة الطباعة المسموح بها"),
            "DOWNLOAD_TEXT": ("download/", "تنزيل نسخة النص المسموح بها"),
        }
        for denied, (path, label) in routes.items():
            with self.subTest(action=denied):
                removed = self.reader_authority.grants.pop(denied)
                page = self.client.get(self.url)
                self.assertContains(page, self.publication.body)
                self.assertNotContains(page, label)
                self.assertEqual(self.client.get(self.url + path).status_code, 404)
                for allowed, (other_path, _) in routes.items():
                    if allowed != denied:
                        self.assertEqual(self.client.get(self.url + other_path).status_code, 200)
                self.reader_authority.grants[denied] = removed
        self.reader_authority.grants.clear()
        self.assertContains(self.client.get(self.url), "لا توجد أدوات متاحة")
        self.assertEqual(
            self.client.get(f"/library-preview/editions/{self.publication.pk}/").status_code, 200
        )

    def test_download_is_exact_safe_text_without_private_history_or_audio(self):
        before = core_state(self.common["case_id"])
        response = self.client.get(self.url + "download/")
        self.assertEqual(response.status_code, 200, response.content)
        with services.reader_projection(self.publication.pk, action="DOWNLOAD_TEXT") as row:
            expected = services.text_copy(row)
        self.assertEqual(response.content, expected)
        text = response.content.decode("utf-8")
        self.assertIn(self.publication.body, text)
        self.assertIn("لا تتضمن مرفقات", text)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn(self.receipt["public_ref"], text)
        self.assertNotIn("private-original-name", text)
        self.assertNotIn(str(self.part.pk), text)
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="answer-{self.publication.pk}-v1.txt"',
        )
        self.assertEqual(int(response["Content-Length"]), len(expected))
        self.assertEqual(core_state(self.common["case_id"]), before)

    def test_print_has_light_layout_exact_content_and_live_permission_control(self):
        response = self.client.get(self.url + "print/")
        self.assertContains(response, self.publication.body)
        self.assertContains(response, 'class="reader-print"')
        self.assertContains(response, self.url + "print-permission/")
        self.assertNotContains(response, "PRIVATE")
        stylesheet = self.client.get("/library-preview/reading/tools.css").content.decode()
        self.assertIn("color-scheme:light", stylesheet)
        self.assertIn("@media print", stylesheet)
        self.assertIn(".print-tools{display:none", stylesheet)

    def test_flags_and_missing_authority_fail_closed_without_affecting_public_text(self):
        for setting, value in (
            ("FATWA_PUBLIC_READER_TOOLS_ENABLED", False),
            ("FATWA_PUBLIC_READER_TOOLS_AUTHORITY", None),
        ):
            with self.subTest(setting=setting), override_settings(**{setting: value}):
                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(self.client.get(self.url + "download/").status_code, 404)
                self.assertEqual(
                    self.client.get(
                        f"/library-preview/editions/{self.publication.pk}/"
                    ).status_code,
                    200,
                )
        with override_settings(
            FATWA_PUBLIC_ANSWER_MEDIA_ENABLED=False, FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY=None
        ):
            self.assertEqual(self.client.get(self.url + "download/").status_code, 200)

    def test_grant_actor_must_be_current_same_epoch_and_scoped_mufti(self):
        original = self.directory.identities["publisher"]
        for change in (
            {"active": False},
            {"case_keys": frozenset()},
            {"auth_epoch": "epoch-2"},
            {"role": "REQUESTER"},
        ):
            with self.subTest(change=change):
                self.directory.identities["publisher"] = replace(original, **change)
                self.assertEqual(self.client.get(self.url + "download/").status_code, 404)
                self.directory.identities["publisher"] = original
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            self.assertEqual(self.client.get(self.url + "download/").status_code, 404)

    def test_wrong_exact_publication_hash_actor_or_deadline_cannot_be_reused(self):
        original = self.reader_authority.grants["DOWNLOAD_TEXT"]
        for change in (
            {"publication_id": str(uuid.uuid4())},
            {"content_sha256": "0" * 64},
            {"action": "PRINT"},
            {"subject_id": "unregistered"},
            {"provider_id": "different"},
            {"auth_epoch": "epoch-2"},
            {"valid_until": timezone.now() - timedelta(seconds=1)},
            {"valid_until": timezone.now() + timedelta(hours=2)},
        ):
            with self.subTest(change=change):
                self.reader_authority.grants["DOWNLOAD_TEXT"] = replace(original, **change)
                self.assertEqual(self.client.get(self.url + "download/").status_code, 404)
        self.reader_authority.grants["DOWNLOAD_TEXT"] = original
        self.assertEqual(self.client.get(self.url + "download/").status_code, 200)

    def test_late_tool_grant_or_identity_revocation_rejects_whole_response(self):
        for revoke in (
            lambda: self.reader_authority.grants.pop("PRINT"),
            lambda: self.directory.identities.__setitem__(
                "publisher", replace(self.directory.identities["publisher"], active=False)
            ),
        ):
            grants = dict(self.reader_authority.grants)
            actor = self.directory.identities["publisher"]
            with self.assertRaises(preview.PreviewUnavailable):
                with services.reader_projection(self.publication.pk):
                    revoke()
            self.reader_authority.grants = grants
            self.directory.identities["publisher"] = actor

    def test_value_equal_authority_replacement_does_not_pass_object_pin(self):
        class EqualAuthority(FixtureAuthority):
            def __eq__(self, other):
                return True

        replacement = EqualAuthority(self.publication, self.directory.provider_id)
        replacement.grants = dict(self.reader_authority.grants)
        with self.assertRaises(preview.PreviewUnavailable):
            with services.reader_projection(self.publication.pk):
                configured = override_settings(FATWA_PUBLIC_READER_TOOLS_AUTHORITY=replacement)
                configured.enable()
                self.addCleanup(configured.disable)

    def test_later_permission_callback_cannot_remove_an_earlier_action(self):
        def revoke(values):
            if values["action"] == "DOWNLOAD_TEXT":
                self.reader_authority.grants.pop("SAVE_REFERENCE", None)

        self.reader_authority.hook = revoke
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_actual_template_withdrawal_is_rolled_back_and_never_emitted(self):
        original = views.render

        def withdraw(request, template, context):
            rendered = original(request, template, context)
            publication.act(
                **{**self.common, "subject_id": "publisher"},
                edition_id=str(self.publication.pk),
                action="WITHDRAW",
            )
            return rendered

        with patch.object(views, "render", side_effect=withdraw):
            response = self.client.get(self.url + "print/")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.publication.body, status_code=404)
        self.assertFalse(
            PublicationAction.objects.filter(edition=self.publication, action="WITHDRAW").exists()
        )

    def test_final_source_callback_cannot_revoke_tool_after_tool_checks(self):
        original = preview._recheck
        armed = []

        def changed(selected):
            original(selected)
            if armed:
                self.reader_authority.grants.pop("DOWNLOAD_TEXT", None)

        with patch.object(preview, "_recheck", side_effect=changed):
            with self.assertRaises(preview.PreviewUnavailable):
                with services.reader_projection(self.publication.pk, action="DOWNLOAD_TEXT") as row:
                    self.assertEqual(row["actions"], ["DOWNLOAD_TEXT"])
                    armed.append(True)

    def test_withdrawn_text_never_survives_via_saved_reference_or_other_tool(self):
        publication.act(
            **{**self.common, "subject_id": "publisher"},
            edition_id=str(self.publication.pk),
            action="WITHDRAW",
        )
        for path in ("", "save-reference/", "share-link/", "print/", "download/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(self.url + path).status_code, 404)
        self.assertEqual(self.client.get("/library-preview/reading/saved/").status_code, 200)

    def test_http_guard_assets_queries_and_head_preserve_protected_boundary(self):
        response = self.client.get(self.url)
        csp = response["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)
        for excluded in ("unsafe-eval", "unsafe-inline", "https:", "blob:", "worker-src"):
            self.assertNotIn(excluded, csp)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.assertEqual(self.client.get(self.url + "?private_case=forged").status_code, 400)
        self.assertEqual(self.client.get(self.url, REMOTE_ADDR="203.0.113.10").status_code, 403)
        response = self.client.head(self.url + "download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        for name in ("tools.css", "tools.js"):
            self.assertEqual(self.client.get("/library-preview/reading/" + name).status_code, 200)
        with override_settings(FATWA_PUBLIC_READER_TOOLS_ENABLED=False):
            self.assertEqual(self.client.get("/library-preview/reading/tools.js").status_code, 404)
