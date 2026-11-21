"""Whole-request contracts for owner point 383, before its implementation.

These tests use actual native forms, current identities, immutable originals and
PostgreSQL. No link issuer, response, grant or byte reader is replaced by a fake.
The unsigned baseline must fail the signature requirements below.
"""

import re
from dataclasses import replace
from datetime import timedelta
from html import unescape
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as answer_media
from apps.answer_media.models import AnswerManifest, AnswerPart
from apps.answer_media.tests import audio_fixture
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.case_attachments.tests import new_case
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.private_media import links
from apps.public_answer_media import test_http as recording_http
from apps.public_answer_media.test_support import FEATURES as RECORDING_FEATURES
from apps.public_answer_media.test_support import MediaFixture, audio
from apps.research_library import services as library
from apps.research_library import test_http as library_http
from apps.research_library.test_support import FEATURES as LIBRARY_FEATURES
from apps.research_library.test_support import LibraryFixture
from tests.casework.test_http import WEB_SETTINGS, Directory, post

LINK_SETTINGS = {
    "FATWA_PRIVATE_MEDIA_LINKS_ENABLED": True,
    # Fabricated development keys are never production credentials.
    "FATWA_PRIVATE_MEDIA_LINKS_KEY": "synthetic-private-links-only-" + "a" * 40,
    "FATWA_PRIVATE_MEDIA_LINKS_EPOCH": "synthetic-links-epoch-1",
    "FATWA_PRIVATE_MEDIA_LINKS_TTL_SECONDS": 120,
}
FEATURES = {
    **WEB_SETTINGS,
    **LINK_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    "MIDDLEWARE": ["apps.private_media.links.PrivateMediaResponses", *WEB_SETTINGS["MIDDLEWARE"]],
}


def client():
    return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")


class LinkAssertions:
    def signed_url(self, response, path):
        self.assertEqual(response.status_code, 200, response.content)
        urls = [
            unescape(value)
            for value in re.findall(r'(?:href|src)="([^"]+)"', response.content.decode())
            if urlsplit(unescape(value)).path == path
        ]
        self.assertTrue(urls, f"native page must expose the authorized media path: {path}")
        for value in urls:
            self.check_signed_url(value, path)
        return urls[0]

    def check_signed_url(self, value, path):
        parsed = urlsplit(value)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path), ("", "", path))
        fields = parse_qs(parsed.query, keep_blank_values=True)
        self.assertEqual(set(fields), {"access"}, "private media URL needs an exact signed ticket")
        self.assertEqual(len(fields["access"]), 1)
        self.assertTrue(32 <= len(fields["access"][0]) <= 1800)
        self.assertLessEqual(len(value), 2048)

    def denied_file(self, response, raw, *, status=404):
        self.assertEqual(response.status_code, status, response.content)
        self.assertNotIn(raw, response.content)
        for name in ("Content-Disposition", "Content-Range", "ETag", "X-Content-SHA256"):
            self.assertNotIn(name, response)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def exact_range(self, browser, url, raw):
        full = browser.get(url)
        self.assertEqual(full.status_code, 200, full.content)
        self.assertEqual(full.content, raw)
        self.assertEqual(full["Accept-Ranges"], "bytes")
        self.assertIn("no-store", full["Cache-Control"])
        self.assertEqual(full["Referrer-Policy"], "no-referrer")
        self.assertIn("sandbox", full["Content-Security-Policy"])
        partial = browser.get(url, HTTP_RANGE="bytes=4-19")
        self.assertEqual(partial.status_code, 206, partial.content)
        self.assertEqual(partial.content, raw[4:20])
        self.assertEqual(partial["Content-Range"], f"bytes 4-19/{len(raw)}")
        suffix = browser.get(url, HTTP_RANGE="bytes=-8")
        self.assertEqual(suffix.status_code, 206)
        self.assertEqual(suffix.content, raw[-8:])
        head = browser.head(url, HTTP_RANGE="bytes=4-19")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(int(head["Content-Length"]), len(raw))
        invalid = browser.get(url, HTTP_RANGE="bytes=0-1,4-5")
        self.assertEqual(invalid.status_code, 416)
        self.assertEqual(invalid.content, b"")


class PrivateOriginalFixture:
    def setUp(self):
        super().setUp()
        self.receipt = new_case()
        self.directory = Directory()
        self.directory.projection_epoch = lambda: repr(self.directory.current)
        self.directory.grant(self.receipt["public_ref"])
        configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.raw = audio_fixture()["raw"]
        self.attachment = attachments.upload(
            token=self.receipt["token"],
            raw=self.raw,
            filename="private-question.wav",
            media_type="audio/wav",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        saved = answer_media.save_multipart_answer(
            **self.common,
            text="PRIVATE synthetic original answer",
            files=[audio_fixture()],
            expected_revision=2,
            expected_evidence_version=2,
        )
        approved = cases.record_decision(
            **self.common,
            answer_id=saved["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=3,
            expected_evidence_version=2,
        )
        manifest = AnswerManifest.objects.get(answer_id=approved["approved_answer_id"])
        answer_media.release_private(
            **self.common,
            expected_revision=4,
            expected_evidence_version=2,
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )
        self.part = AnswerPart.objects.get(manifest=manifest, ordinal=2)
        self.requester = self.requester_for(self.receipt)
        self.staff = self.staff_for()

    def requester_for(self, receipt):
        browser = client()
        page = browser.get("/casework/status/")
        result = post(
            browser, "/casework/status/", {"action": "unlock", "token": receipt["token"]}, page
        )
        self.assertEqual(result.status_code, 303, result.content)
        return browser

    def staff_for(self):
        browser = client()
        page = browser.get("/casework/staff/login/")
        result = post(
            browser, "/casework/staff/login/", {"credential": self.directory.credential}, page
        )
        self.assertEqual(result.status_code, 303, result.content)
        return browser

    def answer_url(self, browser, audience):
        home = f"/casework/{audience}/"
        values = {"action": "answer_media"}
        if audience == "staff":
            values["case_ref"] = self.receipt["public_ref"]
        page = post(browser, home, values, browser.get(home))
        return self.signed_url(page, f"{home}answer-media/{self.part.pk}/")

    def attachment_url(self, browser, audience, *, download=False):
        home = f"/casework/{audience}/"
        values = {
            "action": "attachment_download" if download else "attachment_preview",
            "attachment_id": self.attachment["id"],
        }
        if audience == "staff":
            values["case_ref"] = self.receipt["public_ref"]
        page = post(browser, home, values, browser.get(home))
        path = f"{home}attachments/{self.attachment['id']}/"
        if download:
            self.assertEqual(page.status_code, 303, "download POST must issue a bounded URL")
            self.check_signed_url(page["Location"], path)
            return page["Location"]
        return self.signed_url(page, path)

    def originals(self):
        return (
            list(AnswerRevision.objects.values_list("pk", "text", "text_sha256")),
            list(AnswerPart.objects.values_list("pk", "sha256", "original")),
            list(CaseAttachment.objects.values_list("pk", "sha256", "original")),
        )


@override_settings(**FEATURES)
class SignedPrivateOriginalTests(LinkAssertions, PrivateOriginalFixture, TransactionTestCase):
    def test_enabled_gate_requires_ticket_even_for_an_authorized_existing_session(self):
        for audience, browser in (("staff", self.staff), ("status", self.requester)):
            for kind, identifier in (
                ("answer-media", str(self.part.pk)),
                ("attachments", self.attachment["id"]),
            ):
                path = f"/casework/{audience}/{kind}/{identifier}/"
                for method in (browser.get, browser.head):
                    with self.subTest(path=path, method=method.__name__):
                        self.denied_file(method(path), self.raw)

    def test_native_answer_and_attachment_urls_return_exact_full_head_and_range_bytes(self):
        original = self.originals()
        for audience, browser in (("staff", self.staff), ("status", self.requester)):
            for issue in (self.answer_url, self.attachment_url):
                with self.subTest(audience=audience, source=issue.__name__):
                    self.exact_range(browser, issue(browser, audience), self.raw)
        self.assertEqual(self.originals(), original)

    def test_link_possession_does_not_authorize_anonymous_other_case_or_same_actor_new_session(
        self,
    ):
        requester_url = self.answer_url(self.requester, "status")
        other_case = self.requester_for(new_case())
        same_case_other_session = self.requester_for(self.receipt)
        for browser in (client(), other_case, same_case_other_session, self.staff):
            self.denied_file(browser.get(requester_url), self.raw)
            self.denied_file(browser.get(requester_url, HTTP_RANGE="bytes=0-7"), self.raw)
        staff_url = self.answer_url(self.staff, "staff")
        self.denied_file(self.staff_for().get(staff_url), self.raw)
        self.exact_range(self.staff, staff_url, self.raw)

    def test_ticket_cannot_move_between_objects_audiences_or_download_purposes(self):
        inline = self.attachment_url(self.requester, "status")
        download = self.attachment_url(self.requester, "status", download=True)
        self.assertNotEqual(inline, download)
        self.assertIn("inline", self.requester.get(inline)["Content-Disposition"])
        self.assertIn("attachment", self.requester.get(download)["Content-Disposition"])
        other_path = f"/casework/status/answer-media/{self.part.pk}/"
        moved = urlunsplit(("", "", other_path, urlsplit(inline).query, ""))
        self.denied_file(self.requester.get(moved), self.raw)
        moved = inline.replace("/status/", "/staff/")
        self.denied_file(self.staff.get(moved), self.raw)

    def test_expiration_key_rotation_and_epoch_rotation_require_new_current_urls(self):
        issued = timezone.now()
        url = self.answer_url(self.requester, "status")
        later = issued + timedelta(seconds=121)
        with (
            patch("django.utils.timezone.now", return_value=later),
            patch("time.time", return_value=later.timestamp()),
        ):
            self.denied_file(self.requester.get(url), self.raw)
            self.exact_range(self.requester, self.answer_url(self.requester, "status"), self.raw)
        for config in (
            {"FATWA_PRIVATE_MEDIA_LINKS_KEY": "synthetic-rotated-links-only-" + "b" * 40},
            {"FATWA_PRIVATE_MEDIA_LINKS_EPOCH": "synthetic-links-epoch-2"},
        ):
            with override_settings(**config):
                self.denied_file(self.requester.get(url), self.raw)
                self.exact_range(
                    self.requester, self.answer_url(self.requester, "status"), self.raw
                )

    def test_staff_epoch_scope_and_active_role_are_rechecked_after_issuing_url(self):
        url = self.answer_url(self.staff, "staff")
        actor = self.directory.current
        for changed in (
            replace(actor, auth_epoch="revoked"),
            replace(actor, case_keys=frozenset()),
            replace(actor, active=False),
            replace(actor, role="ORGANIZER"),
        ):
            self.directory.current = changed
            for method in (self.staff.get, self.staff.head):
                self.denied_file(method(url, HTTP_RANGE="bytes=0-7"), self.raw)
        self.directory.current = actor
        self.exact_range(self.staff, url, self.raw)

    def test_requester_revocation_between_ranges_denies_head_and_conditional_reads(self):
        url = self.answer_url(self.requester, "status")
        first = self.requester.get(url, HTTP_RANGE="bytes=0-15")
        self.assertEqual(first.status_code, 206)
        cases.revoke_access(
            **self.common, requester_id=Case.objects.get(pk=self.receipt["case_id"]).requester_id
        )
        self.denied_file(self.requester.get(url, HTTP_RANGE="bytes=16-31"), self.raw)
        self.denied_file(self.requester.get(url, HTTP_RANGE="bytes=999999-"), self.raw)
        self.denied_file(self.requester.head(url), self.raw)
        self.denied_file(self.requester.get(url, HTTP_IF_NONE_MATCH=first["ETag"]), self.raw)

    def test_new_evidence_closes_previous_answer_link_without_changing_original_bytes(self):
        url = self.answer_url(self.requester, "status")
        original = self.originals()
        cases.add_followup(
            token=self.receipt["token"],
            text="new synthetic material facts",
            expected_revision=4,
            synthetic_fixtures_only=True,
        )
        self.denied_file(self.requester.get(url), self.raw)
        self.denied_file(self.requester.get(url, HTTP_RANGE="bytes=0-15"), self.raw)
        self.assertEqual(self.originals(), original)

    def test_tampered_duplicate_and_unknown_query_values_never_expose_file_metadata(self):
        url = self.answer_url(self.requester, "status")
        parsed = urlsplit(url)
        ticket = parse_qs(parsed.query)["access"][0]
        tampered = ticket[:-1] + ("A" if ticket[-1] != "A" else "B")
        target = urlunsplit(("", "", parsed.path, urlencode({"access": tampered}), ""))
        self.denied_file(self.requester.get(target), self.raw)
        for query in (
            urlencode([("access", ticket), ("access", ticket)]),
            urlencode({"access": ticket, "purpose": "DOWNLOAD"}),
            urlencode({"access": ticket, "filename": "private-answer.wav"}),
        ):
            target = urlunsplit(("", "", parsed.path, query, ""))
            self.denied_file(self.requester.get(target), self.raw, status=400)

    def test_enabled_missing_or_malformed_key_and_lifetime_never_reuse_unsigned_reader(self):
        path = f"/casework/status/answer-media/{self.part.pk}/"
        for config in (
            {"FATWA_PRIVATE_MEDIA_LINKS_KEY": None},
            {"FATWA_PRIVATE_MEDIA_LINKS_KEY": "short"},
            {"FATWA_PRIVATE_MEDIA_LINKS_KEY": " " * 40},
            {"FATWA_PRIVATE_MEDIA_LINKS_EPOCH": ""},
            {"FATWA_PRIVATE_MEDIA_LINKS_TTL_SECONDS": True},
            {"FATWA_PRIVATE_MEDIA_LINKS_TTL_SECONDS": 0},
            {"FATWA_PRIVATE_MEDIA_LINKS_TTL_SECONDS": 901},
        ):
            with override_settings(**config):
                self.denied_file(self.requester.get(path), self.raw)

    def test_late_private_release_gate_change_discards_an_already_built_range(self):
        url = self.answer_url(self.requester, "status")
        build = links._range_response
        revoked = override_settings(FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=False)

        def close_release(*args, **kwargs):
            result = build(*args, **kwargs)
            revoked.enable()
            return result

        try:
            with patch.object(links, "_range_response", side_effect=close_release):
                self.denied_file(self.requester.get(url, HTTP_RANGE="bytes=0-10"), self.raw)
        finally:
            revoked.disable()
        self.exact_range(self.requester, url, self.raw)

    def test_disabled_new_feature_preserves_existing_private_access_checks(self):
        with override_settings(FATWA_PRIVATE_MEDIA_LINKS_ENABLED=False):
            path = f"/casework/status/answer-media/{self.part.pk}/"
            self.assertEqual(self.requester.get(path).content, self.raw)
            denied = client().get(path)
            self.assertEqual(denied.status_code, 404)
            self.assertNotIn(self.raw, denied.content)
            self.assertIn("no-store", denied["Cache-Control"])


@override_settings(
    **{
        **LIBRARY_FEATURES,
        **LINK_SETTINGS,
        "MIDDLEWARE": [
            "apps.private_media.links.PrivateMediaResponses",
            *LIBRARY_FEATURES["MIDDLEWARE"],
        ],
    }
)
class SignedLibraryTests(LinkAssertions, LibraryFixture, TransactionTestCase):
    login = library_http.LibraryHTTPTests.login
    action = library_http.LibraryHTTPTests.action

    def selected(self, *, uses=None):
        raw = b"PRIVATE synthetic library source\r\nexact original bytes"
        record = self.approve(
            self.write(file_bytes=raw, filename="private-source.txt", media_type="text/plain"),
            uses=uses or ["READ", "DOWNLOAD"],
        )
        browser, home = self.login()
        page = self.action(browser, home, "rl_item", version_id=record["version_id"])
        return browser, record, page, raw

    def test_library_native_inline_and_download_urls_bind_purpose_and_exact_version(self):
        browser, record, page, raw = self.selected()
        prefix = f"/casework/staff/library/{record['version_id']}/"
        inline = self.signed_url(page, prefix + "file/")
        download = self.signed_url(page, prefix + "download/")
        self.exact_range(browser, inline, raw)
        self.assertIn("attachment", browser.get(download)["Content-Disposition"])
        swapped = urlunsplit(("", "", prefix + "download/", urlsplit(inline).query, ""))
        self.denied_file(browser.get(swapped), raw)
        other = self.approve(
            self.write(file_bytes=raw, filename="same-bytes.txt", media_type="text/plain"),
            uses=["READ", "DOWNLOAD"],
        )
        self.denied_file(
            browser.get(inline.replace(record["version_id"], other["version_id"])), raw
        )

    def test_current_library_download_denial_does_not_borrow_inline_permission(self):
        browser, record, page, raw = self.selected()
        prefix = f"/casework/staff/library/{record['version_id']}/"
        inline = self.signed_url(page, prefix + "file/")
        download = self.signed_url(page, prefix + "download/")
        self.authority.denied.add("DOWNLOAD")
        self.denied_file(browser.get(download, HTTP_RANGE="bytes=0-10"), raw)
        self.denied_file(browser.head(download), raw)
        self.exact_range(browser, inline, raw)

    def test_library_late_revocation_during_actual_blob_read_discards_the_whole_response(self):
        browser, record, page, raw = self.selected()
        url = self.signed_url(page, f"/casework/staff/library/{record['version_id']}/file/")
        read = library._raw

        def revoke_after_read(blob):
            result = read(blob)
            self.authority.denied.add("READ")
            return result

        with patch.object(library, "_raw", side_effect=revoke_after_read):
            self.denied_file(browser.get(url, HTTP_RANGE="bytes=0-10"), raw)

    def test_library_late_revocation_after_range_construction_discards_bytes_and_headers(self):
        browser, record, page, raw = self.selected()
        url = self.signed_url(page, f"/casework/staff/library/{record['version_id']}/file/")
        build = links._range_response

        def revoke_after_build(*args, **kwargs):
            result = build(*args, **kwargs)
            self.authority.denied.add("READ")
            return result

        with patch.object(links, "_range_response", side_effect=revoke_after_build):
            self.denied_file(browser.get(url, HTTP_RANGE="bytes=0-10"), raw)
        self.authority.denied.clear()
        self.exact_range(browser, url, raw)


@override_settings(
    **{
        **RECORDING_FEATURES,
        **LINK_SETTINGS,
        "MIDDLEWARE": [
            "apps.private_media.links.PrivateMediaResponses",
            *RECORDING_FEATURES["MIDDLEWARE"],
        ],
    }
)
class SignedRecordingTests(LinkAssertions, MediaFixture, TransactionTestCase):
    client_for = recording_http.MediaHTTPTests.client_for
    desk = recording_http.MediaHTTPTests.desk

    def setUp(self):
        super().setUp()
        self.client = self.client_for("editor")

    def test_private_recording_parts_use_signed_urls_and_current_rights_for_each_range(self):
        path = f"/casework/staff/recording-parts/{self.part.pk}/audio/"
        url = self.signed_url(self.desk(), path)
        self.exact_range(self.client, url, audio())
        self.rights.denied.add("editor")
        self.denied_file(self.client.get(url, HTTP_RANGE="bytes=0-10"), audio())
        self.denied_file(self.client.head(url), audio())

    def test_private_transcript_playback_keeps_fragment_and_rechecks_current_exact_version(self):
        row = self.review(self.save())
        path = f"/casework/staff/recording-transcripts/{row['id']}/audio/"
        segment = self.client.get(f"/casework/staff/recording-transcripts/{row['id']}/segments/0/")
        url = self.signed_url(segment, path)
        self.assertEqual(urlsplit(url).fragment, "t=1,2.5")
        self.exact_range(self.client, url, audio())
        self.authority.denied.add("READ_TRANSCRIPT")
        self.denied_file(self.client.get(url, HTTP_RANGE="bytes=0-10"), audio())

    def test_new_browser_cannot_use_signed_recording_even_with_same_current_identity(self):
        url = self.signed_url(self.desk(), f"/casework/staff/recording-parts/{self.part.pk}/audio/")
        other = self.client_for("editor")
        self.denied_file(other.get(url, HTTP_RANGE="bytes=0-10"), audio())
        self.exact_range(self.client, url, audio())

    def test_late_recording_permission_withdrawal_after_range_build_is_not_returned(self):
        url = self.signed_url(self.desk(), f"/casework/staff/recording-parts/{self.part.pk}/audio/")
        build = links._range_response

        def revoke_after_build(*args, **kwargs):
            result = build(*args, **kwargs)
            self.authority.denied.add("READ_TRANSCRIPT")
            return result

        with patch.object(links, "_range_response", side_effect=revoke_after_build):
            self.denied_file(self.client.get(url, HTTP_RANGE="bytes=0-10"), audio())
