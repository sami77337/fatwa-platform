"""Focused PostgreSQL privacy, canonical composition and native form contracts."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.case_attachments import services as attachments
from apps.case_citations import services as citations
from apps.case_citations.tests import source_fixture
from apps.casework import delivery
from apps.casework import services as cases
from apps.casework.models import CaseEvent
from apps.delivery_queue import services as queue
from apps.delivery_queue.models import DeliveryIntent
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_http import hidden, post

from . import services
from .test_support import PORTAL_SETTINGS, PortalFixture

URL = "/casework/status/"


@override_settings(**PORTAL_SETTINGS)
class SnapshotTests(PortalFixture, TransactionTestCase):
    def snapshot(self):
        return services.snapshot(token=self.a["token"], synthetic_fixtures_only=True)

    def test_six_states_distinguish_current_approval_availability_acceptance_and_signed_parts(self):
        self.assertEqual(self.snapshot()["answer_state"], "UNDER_REVIEW")
        self.approve()
        self.assertEqual(self.snapshot()["answer_state"], "APPROVED_UNAVAILABLE")
        self.assertIsNone(self.snapshot()["answer"])
        self.release()
        self.assertEqual(self.snapshot()["answer_state"], "PRIVATE_AVAILABLE")
        self.stage()
        self.assertEqual(self.snapshot()["delivery"]["state"], "NOT_PROVEN")
        first = self.reserve()
        part = self.resolve(first)
        self.outcome(first, part, "ACCEPTED")
        self.assertEqual(self.snapshot()["delivery"]["state"], "PROVIDER_ACCEPTED")
        self.assertFalse(self.snapshot()["delivery"]["summary"]["delivery_verified"])
        self.outcome(first, part, "DELIVERED")
        self.assertEqual(self.snapshot()["delivery"]["state"], "UNRESOLVED")
        while lease := self.reserve():
            self.outcome(lease, self.resolve(lease), "DELIVERED")
        result = self.snapshot()
        self.assertEqual(result["delivery"]["state"], "SIGNED_DELIVERED")
        self.assertEqual(result["delivery"]["summary"]["verified_parts"], 3)
        self.assertFalse(result["read_confirmed"])
        self.assertFalse(result["delivery"]["read_confirmed"])

    def test_partial_failure_expiry_and_capability_change_never_report_complete(self):
        self.approve()
        self.release()
        self.stage()
        lease = self.reserve()
        self.outcome(lease, self.resolve(lease), "FAILED")
        self.assertEqual(self.snapshot()["delivery"]["state"], "UNRESOLVED")
        self.reserve()
        queue.quarantine_expired_leases(now=timezone.now() + timedelta(minutes=2))
        self.assertEqual(self.snapshot()["delivery"]["summary"]["unresolved_parts"], 1)
        self.profile = replace(self.profile, max_media_bytes=100000)
        self.assertIsNone(self.snapshot()["delivery"]["summary"])
        self.assertEqual(self.snapshot()["delivery"]["state"], "UNRESOLVED")

    def test_current_citations_parts_and_conversation_exclude_drafts_research_notes_and_audit(self):
        edition = source_fixture()
        source = citations.read_source(**self.staff(), edition_id=edition, source_row_id=2)
        citations.save_cited_answer(
            **self.staff(),
            text="SECRET_DRAFT",
            expected_revision=1,
            expected_evidence_version=1,
            selections=[
                dict(
                    edition_id=edition,
                    source_row_id=2,
                    source_sha256=source["source_sha256"],
                    editorial_note="SECRET_RESEARCH_NOTE",
                )
            ],
        )
        self.assertNotIn("SECRET_DRAFT", str(self.snapshot()))
        self.approve()
        self.release()
        result = self.snapshot()
        self.assertEqual(len(result["answer"]["parts"]), 2)
        self.assertEqual(result["answer"]["citations"][0]["heading_title"], "فَرْعٌ تَجْرِيبِيّ")
        for forbidden in (
            "SECRET_DRAFT",
            "SECRET_RESEARCH_NOTE",
            "synthetic-mufti",
            "auth_epoch",
            "source_event_id",
            "plan_sha256",
            "SAVE_ANSWER",
            "APPROVE",
        ):
            self.assertNotIn(forbidden, str(result))
        self.assertEqual(result["history"][0]["text"], "  سؤال اصطناعي حرفي\na")

    def test_new_facts_new_answer_and_revoked_authority_hide_old_answer_and_sources(self):
        self.approve()
        self.release()
        self.assertIsNotNone(self.snapshot()["answer"])
        self.directory.epoch = "revoked"
        self.assertIsNone(self.snapshot()["answer"])
        self.directory.epoch = "epoch-1"
        current = cases.read_case(**self.staff())
        cases.add_followup(
            token=self.a["token"],
            text="وقائع جديدة",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        self.assertIsNone(self.snapshot()["answer"])
        self.assertEqual(self.snapshot()["history"][-1]["text"], "وقائع جديدة")
        self.approve()
        self.release()
        self.save()
        self.assertIsNone(self.snapshot()["answer"])

    def test_disabled_release_missing_media_and_mid_read_revocation_fail_closed(self):
        self.approve()
        self.release()
        with override_settings(FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=False):
            self.assertIsNone(self.snapshot()["answer"])
        with patch.object(
            media, "requester_snapshot", side_effect=cases.CaseConflict("storage_failed")
        ):
            self.assertIsNone(self.snapshot()["answer"])
        original = media.requester_snapshot

        def revoke(**kwargs):
            result = original(**kwargs)
            self.directory.epoch = "revoked-during-read"
            return result

        with patch.object(media, "requester_snapshot", side_effect=revoke):
            self.assertIsNone(self.snapshot()["answer"])
        with override_settings(FATWA_REQUESTER_PORTAL_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.snapshot()

    def test_legacy_text_requires_complete_signed_delivery_not_approval_or_acceptance(self):
        CaseDeliveryFixture.approve(self)
        self.assertIsNone(self.snapshot()["answer"])
        prepared = CaseDeliveryFixture.request(self)
        CaseDeliveryFixture.stage(self, receipt=self.receipt(prepared))
        verifier = self.verifier()
        with override_settings(FATWA_CASE_DELIVERY_PROVIDER_VERIFIER=verifier):
            first = CaseDeliveryFixture.reserve(self)
            delivery.record_case_provider_event(
                **self.staff(),
                lease=first,
                event=self.event(first, reported="ACCEPTED"),
                verifier=verifier,
            )
            self.assertIsNone(self.snapshot()["answer"])
            self.assertNotEqual(self.snapshot()["delivery"]["state"], "SIGNED_DELIVERED")
            delivery.record_case_provider_event(
                **self.staff(), lease=first, event=self.event(first), verifier=verifier
            )
            while lease := CaseDeliveryFixture.reserve(self):
                delivery.record_case_provider_event(
                    **self.staff(), lease=lease, event=self.event(lease), verifier=verifier
                )
            result = self.snapshot()
            self.assertEqual(result["answer_state"], "PRIVATE_AVAILABLE")
            self.assertEqual(result["delivery"]["state"], "SIGNED_DELIVERED")
            self.assertEqual(result["answer"]["parts"], [])
            self.assertFalse(result["read_confirmed"])
            with override_settings(FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED=False):
                self.assertIsNone(self.snapshot()["answer"])

    def test_snapshot_refuses_version_change_during_composition(self):
        self.approve()
        self.release()
        original = media.requester_snapshot

        def changed(**kwargs):
            result = original(**kwargs)
            current = cases.read_case(**self.staff())
            cases.add_followup(
                token=self.a["token"],
                text="وقائع تغيرت خلال القراءة",
                expected_revision=current["revision"],
                synthetic_fixtures_only=True,
            )
            return result

        with patch.object(media, "requester_snapshot", side_effect=changed):
            with self.assertRaises(cases.CaseConflict):
                self.snapshot()

    def test_reads_do_not_add_events_delivery_attempts_or_read_receipts(self):
        self.approve()
        self.release()
        self.stage()
        client = self.client_for()
        events = list(CaseEvent.objects.values())
        intents = list(DeliveryIntent.objects.values())
        for _ in range(2):
            page = client.get(URL)
            self.assertEqual(page.status_code, 200)
        part = self.snapshot()["answer"]["parts"][1]
        response = client.get(f"{URL}answer-media/{part['id']}/")
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 0)
        self.assertEqual(list(CaseEvent.objects.values()), events)
        self.assertEqual(list(DeliveryIntent.objects.values()), intents)

    def test_expired_and_cross_case_capabilities_do_not_reveal_content(self):
        self.approve()
        self.release()
        own = self.snapshot()["answer"]["parts"][0]
        other = self.intake("other")
        client = self.client_for(other["token"])
        page = client.get(URL)
        self.assertNotContains(page, "جواب بشري مركب اصطناعي")
        self.assertEqual(client.get(f"{URL}answer-media/{own['id']}/").status_code, 404)
        expired = timezone.now() + timedelta(days=8)
        with patch("apps.casework.services.timezone.now", return_value=expired):
            with self.assertRaises(cases.CaseConflict):
                self.snapshot()


@override_settings(**PORTAL_SETTINGS)
class PortalFormTests(PortalFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = self.client_for()

    def submit_followup(self, page, text="رد اصطناعي"):
        return post(
            self.client,
            URL,
            dict(
                action="followup",
                text=text,
                revision=hidden(page, "revision"),
                form_proof=hidden(page, "form_proof"),
            ),
            page,
        )

    def test_clarification_reply_refresh_and_original_text_share_one_page(self):
        cases.request_clarification(
            **self.staff(), text="استيضاح اصطناعي", expected_revision=1, expected_evidence_version=1
        )
        page = self.client.get(URL)
        self.assertContains(page, "استيضاح ينتظر ردك")
        self.assertNotContains(page, 'name="attachment"')
        response = self.submit_followup(page, "رد <script>alert(1)</script>")
        self.assertEqual(response.status_code, 303)
        page = self.client.get(URL)
        self.assertContains(page, "سؤال اصطناعي حرفي")
        self.assertContains(page, "استيضاح اصطناعي")
        self.assertContains(page, "رد &lt;script&gt;alert(1)&lt;/script&gt;")
        before = CaseEvent.objects.count()
        self.client.get(URL)
        self.assertEqual(CaseEvent.objects.count(), before)

    def test_stale_followup_preserves_text_but_case_switch_does_not_copy_it(self):
        page = self.client.get(URL)
        cases.add_followup(
            token=self.a["token"],
            text="سبق الحفظ",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        failed = self.submit_followup(page, "مسودة لم تحفظ")
        self.assertContains(failed, "مسودة لم تحفظ", status_code=409)
        other = self.intake("other")
        unlock = self.client.get(URL)
        post(self.client, URL, dict(action="unlock", token=other["token"]), unlock)
        rejected = self.submit_followup(failed, "SECRET_OTHER_CASE_DRAFT")
        self.assertEqual(rejected.status_code, 409)
        self.assertNotContains(rejected, "SECRET_OTHER_CASE_DRAFT", status_code=409)

    def test_upload_and_private_file_preserve_facts_and_reject_foreign_or_revoked_reads(self):
        page = self.client.get(URL)
        response = self.client.post(
            URL,
            dict(
                action="attachment_upload",
                revision=hidden(page, "revision"),
                upload_proof=hidden(page, "upload_proof"),
                synthetic_only="yes",
                csrfmiddlewaretoken=hidden(page, "csrfmiddlewaretoken"),
                attachment=SimpleUploadedFile(
                    "question.txt", b"private synthetic text", content_type="text/plain"
                ),
            ),
        )
        self.assertEqual(response.status_code, 303, response.content)
        page = self.client.get(URL)
        self.assertContains(page, "question.txt")
        row = attachments.requester_list(token=self.a["token"], synthetic_fixtures_only=True)[
            "attachments"
        ][0]
        location = f"{URL}attachments/{row['id']}/"
        self.assertEqual(self.client.get(location).content, b"private synthetic text")
        other = self.client_for(self.intake("other")["token"])
        self.assertEqual(other.get(location).status_code, 404)
        cases.revoke_access(**self.staff(), requester_id="requester-a")
        self.assertEqual(self.client.get(location).status_code, 404)
        self.assertNotContains(self.client.get(URL), "question.txt")

    def test_upload_or_followup_closes_existing_answer_and_direct_part_url(self):
        self.approve()
        self.release()
        result = services.snapshot(token=self.a["token"], synthetic_fixtures_only=True)
        location = f"{URL}answer-media/{result['answer']['parts'][0]['id']}/"
        page = self.client.get(URL)
        self.assertContains(page, "جواب بشري مركب اصطناعي")
        self.assertEqual(self.submit_followup(page).status_code, 303)
        self.assertNotContains(self.client.get(URL), "جواب بشري مركب اصطناعي")
        self.assertEqual(self.client.get(location).status_code, 404)

    def test_csrf_query_forged_fields_head_and_cookie_close(self):
        page = self.client.get(URL)
        self.assertIn("no-store", page["Cache-Control"])
        self.assertIn("noindex", page["X-Robots-Tag"])
        self.assertEqual(self.client.head(URL).content, b"")
        self.assertEqual(self.client.post(URL, dict(action="leave")).status_code, 403)
        self.assertEqual(self.client.get(URL + "?token=" + self.a["token"]).status_code, 400)
        self.assertEqual(
            post(
                self.client,
                URL,
                dict(
                    action="followup",
                    text="x",
                    revision="1",
                    form_proof="0" * 64,
                    case_id=self.a["case_id"],
                ),
                page,
            ).status_code,
            400,
        )
        response = post(self.client, URL, dict(action="leave"), page)
        self.assertEqual(response.status_code, 303)
        self.assertNotContains(self.client.get(URL), "سؤال اصطناعي حرفي")

    def test_access_review_keeps_portal_and_has_no_recovery_power(self):
        page = self.client.get(URL)
        response = post(
            self.client,
            URL,
            dict(
                action="request_access_review",
                reason="EXPOSED",
                review_proof=hidden(page, "review_proof"),
            ),
            page,
        )
        self.assertEqual(response.status_code, 303)
        self.assertContains(self.client.get(URL), "طلب المراجعة محفوظ")
        self.assertEqual(
            cases.requester_status(self.a["token"], synthetic_fixtures_only=True)["revision"], 1
        )
