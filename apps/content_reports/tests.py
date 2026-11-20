"""Real PostgreSQL reports, original-content preservation and native HTTP journeys."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.db import IntegrityError, connections, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent, CaseSource
from apps.experimental_publication import services as publication
from apps.knowledge_links.tests import Authority as KnowledgeFixtureAuthority
from apps.requester_portal.test_support import PORTAL_SETTINGS, PortalFixture
from apps.research_workspace.tests import SETTINGS as RESEARCH_SETTINGS
from apps.research_workspace.tests import ResearchFixture
from tests.casework.test_http import hidden, post

from . import services
from .authority import ContentReportAuthority
from .models import ContentReport, ReportEvent

SETTINGS = {
    **PORTAL_SETTINGS,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_CONTENT_REPORTS_ENABLED": True,
}


class FixtureAuthority(ContentReportAuthority):
    def __init__(self, ref, provider="synthetic-case-directory", subject="synthetic-mufti"):
        self.ref, self.provider, self.subject = ref, provider, subject
        self.denied = set()

    def projection_epoch(self):
        return repr((self.ref, self.provider, self.subject, sorted(self.denied)))

    def permits(self, **kw):
        return (
            kw["case_ref"] == self.ref
            and kw["provider_id"] == self.provider
            and kw["subject_id"] == self.subject
            and kw["auth_epoch"] == "epoch-1"
            and kw["action"] in {"READ", "SUBMIT", "TRIAGE", "LINK"}
            and kw["target_kind"] in services.KINDS
            and kw["action"] not in self.denied
        )


class VersionedKnowledgeAuthority(KnowledgeFixtureAuthority):
    def projection_epoch(self):
        return repr((self.ref, self.allow_open))


class ReportFixture(PortalFixture):
    def setUp(self):
        super().setUp()
        self.approve()
        self.release()
        self.report_authority = FixtureAuthority(self.a["public_ref"])
        configured = override_settings(FATWA_CONTENT_REPORTS_AUTHORITY=self.report_authority)
        configured.enable()
        self.addCleanup(configured.disable)

    def context(self):
        revision = cases.read_case(**self.staff())["revision"]
        return services.requester_context(
            token=self.a["token"], expected_revision=revision, synthetic_fixtures_only=True
        )

    def arguments(self, **changes):
        current = cases.read_case(**self.staff())
        return {
            "token": self.a["token"],
            "expected_revision": current["revision"],
            "selected_target": self.context()["targets"][0]["key"],
            "request_key": str(uuid.uuid4()),
            "reason": "BROKEN_LINK",
            "description": "  وصف مشكلة اصطناعي\nكما كتبه السائل  ",
            "evidence_note": "موضع المشكلة وخطوات التحقق دون نسخ الملف",
            "synthetic_fixtures_only": True,
            **changes,
        }

    def report(self, **changes):
        return services.submit_requester(**self.arguments(**changes))

    def advance(self, row, action, **changes):
        return services.advance(
            **self.staff(),
            report_id=row["id"],
            expected_revision=row["revision"],
            request_key=str(uuid.uuid4()),
            action=action,
            **{"action_note": "إجراء بشري اصطناعي موثق", "verification_note": "", **changes},
        )


@override_settings(**SETTINGS)
class RequesterReportTests(ReportFixture, TransactionTestCase):
    def test_exact_answer_and_part_pins_without_source_bytes_or_case_mutation(self):
        before = list(CaseEvent.objects.values()), list(AnswerRevision.objects.values())
        source = CaseSource.objects.get().original_question
        targets = self.context()["targets"]
        self.assertEqual(len(targets), 3)
        for target in targets:
            self.report(selected_target=target["key"])
        self.assertEqual(ContentReport.objects.count(), 3)
        answer = AnswerRevision.objects.get(
            pk=cases.read_case(**self.staff())["approved_answer_id"]
        )
        for row in ContentReport.objects.all():
            self.assertEqual(row.target["answer_id"], str(answer.pk))
            self.assertEqual(row.target["answer_revision"], answer.revision)
            self.assertEqual(row.target["manifest_sha256"], answer.media_manifest.sha256)
            self.assertEqual(row.description, "  وصف مشكلة اصطناعي\nكما كتبه السائل  ")
            self.assertNotIn(answer.text, json.dumps(row.target))
            self.assertNotIn(self.a["token"], str(row.__dict__))
        self.assertEqual(
            before, (list(CaseEvent.objects.values()), list(AnswerRevision.objects.values()))
        )
        self.assertEqual(CaseSource.objects.get().original_question, source)

    def test_duplicate_submission_is_idempotent_but_reused_key_cannot_change_report(self):
        args = self.arguments()
        first, replay = services.submit_requester(**args), services.submit_requester(**args)
        self.assertEqual(first["id"], replay["id"])
        self.assertFalse(replay["created"])
        with self.assertRaises(cases.CaseConflict):
            services.submit_requester(**{**args, "description": "محتوى مختلف"})
        self.assertEqual((ContentReport.objects.count(), ReportEvent.objects.count()), (1, 1))

    def test_concurrent_replay_creates_one_report_and_one_initial_event(self):
        args = self.arguments()

        def submit(_):
            connections.close_all()
            try:
                return services.submit_requester(**args)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit, range(2)))
        self.assertEqual(len({r["id"] for r in results}), 1)
        self.assertEqual(sum(r["created"] for r in results), 1)

    def test_other_case_stale_facts_old_answer_and_revoked_release_cannot_submit(self):
        args = self.arguments()
        other = self.intake("reports-other")
        with self.assertRaises(cases.CaseConflict):
            services.submit_requester(**{**args, "token": other["token"], "expected_revision": 1})
        self.directory.epoch = "revoked"
        with self.assertRaises(cases.CaseConflict):
            services.submit_requester(**args)
        self.directory.epoch = "epoch-1"
        cases.add_followup(
            token=self.a["token"],
            text="وقائع جديدة",
            expected_revision=args["expected_revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            services.submit_requester(**args)
        self.assertEqual(ContentReport.objects.count(), 0)
        self.assertEqual(self.context()["targets"], [])

    def test_revocation_or_followup_during_submission_rolls_back_report_and_nested_writes(self):
        args = self.arguments()
        original = services._create
        revision = args["expected_revision"]

        def changed(*a, **kw):
            result = original(*a, **kw)
            cases.add_followup(
                token=self.a["token"],
                text="وقائع ظهرت خلال الحفظ",
                expected_revision=revision,
                synthetic_fixtures_only=True,
            )
            return result

        with (
            patch.object(services, "_create", side_effect=changed),
            self.assertRaises(cases.CaseConflict),
        ):
            services.submit_requester(**args)
        self.assertEqual(ContentReport.objects.count(), 0)
        self.assertEqual(cases.read_case(**self.staff())["revision"], revision)

        def revoked(*a, **kw):
            result = original(*a, **kw)
            cases.revoke_access(**self.staff(), requester_id="requester-a")
            return result

        with (
            patch.object(services, "_create", side_effect=revoked),
            self.assertRaises(cases.CaseConflict),
        ):
            services.submit_requester(**args)
        self.assertEqual(ContentReport.objects.count(), 0)
        self.assertEqual(
            cases.requester_status(self.a["token"], synthetic_fixtures_only=True)["revision"],
            revision,
        )

    def test_default_off_unacknowledged_and_malformed_reports_make_no_writes(self):
        args = self.arguments()
        with (
            override_settings(FATWA_CONTENT_REPORTS_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            services.submit_requester(**args)
        for change in (
            {"reason": "VOTE_CORRECT"},
            {"description": " "},
            {"description": "x" * 2001},
            {"evidence_note": "\x00"},
            {"request_key": "not-a-key"},
            {"synthetic_fixtures_only": False},
        ):
            with (
                self.subTest(change=tuple(change)),
                self.assertRaises((cases.CaseConflict, ValueError)),
            ):
                services.submit_requester(**{**args, **change})
        self.assertEqual(ContentReport.objects.count(), 0)

    def test_receipt_survives_followup_without_revealing_internal_triage_or_old_source(self):
        row = self.report()
        started = self.advance(row, "START", action_note="PRIVATE TRIAGE DETAIL")
        self.advance(
            started, "RESOLVE", action_note="PRIVATE ACTION", verification_note="PRIVATE VERIFY"
        )
        current = cases.read_case(**self.staff())
        cases.add_followup(
            token=self.a["token"],
            text="وقائع أحدث",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        result = self.context()
        self.assertEqual(result["targets"], [])
        self.assertEqual(result["reports"][0]["state"], "RESOLVED")
        for secret in ("PRIVATE", "synthetic-mufti", "provider_id", "answer_id", "sha256"):
            self.assertNotIn(secret, str(result))

    def test_immutable_initial_report_and_history_database_guards(self):
        row = self.report()
        for operation in (
            lambda: ContentReport.objects.filter(pk=row["id"]).update(description="changed"),
            lambda: ReportEvent.objects.filter(report_id=row["id"]).update(state="RESOLVED"),
            lambda: ReportEvent.objects.filter(report_id=row["id"]).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportEvent.objects.create(
                report_id=row["id"],
                sequence=2,
                request_key=uuid.uuid4(),
                action="RESOLVE",
                state="RESOLVED",
                action_note="x",
                verification_note="y",
                subject_id="a",
                provider_id="b",
                auth_epoch="c",
            )
        self.assertEqual(ReportEvent.objects.count(), 1)

    def test_human_lifecycle_requires_action_verification_and_current_scoped_grant(self):
        row = self.report()
        with self.assertRaises(cases.CaseConflict):
            self.advance(row, "RESOLVE", verification_note="تحقق")
        started = self.advance(row, "START")
        with self.assertRaises(cases.CaseConflict):
            self.advance(started, "RESOLVE")
        with self.assertRaises(cases.CaseConflict):
            self.advance(row, "START")
        self.report_authority.denied.add("TRIAGE")
        with self.assertRaises(cases.CaseConflict):
            self.advance(started, "RESOLVE", verification_note="تحقق")
        self.report_authority.denied.clear()
        closed = self.advance(started, "RESOLVE", verification_note="اختبار بشري موثق")
        reopened = self.advance(closed, "REOPEN")
        started_again = self.advance(reopened, "START")
        dismissed = self.advance(
            started_again, "DISMISS", verification_note="علة عدم المتابعة موثقة"
        )
        self.assertEqual(dismissed["state"], "DISMISSED")
        self.assertFalse(dismissed["content_changed"])
        self.assertEqual(ReportEvent.objects.count(), 6)

    def test_repeat_links_keep_both_reports_and_deny_other_case_or_target(self):
        one, two = self.report(), self.report()
        linked = self.advance(one, "LINK", related_report_id=two["id"])
        self.assertEqual(linked["state"], "OPEN")
        self.assertEqual(ContentReport.objects.count(), 2)
        self.assertEqual(ReportEvent.objects.filter(report_id=two["id"]).count(), 1)
        with self.assertRaises(cases.CaseConflict):
            self.advance(two, "LINK", related_report_id=one["id"])
        different = self.report(selected_target=self.context()["targets"][1]["key"])
        with self.assertRaises(cases.CaseConflict):
            self.advance(linked, "LINK", related_report_id=different["id"])
        other = self.intake("triage-other")
        with self.assertRaises((cases.CaseConflict, ValueError)):
            services.advance(
                **self.staff(other),
                report_id=one["id"],
                expected_revision=2,
                request_key=str(uuid.uuid4()),
                action="START",
                action_note="x",
            )

    def test_triage_replay_and_late_authority_revocation_preserve_committed_history(self):
        row = self.report()
        args = dict(
            **self.staff(),
            report_id=row["id"],
            expected_revision=1,
            request_key=str(uuid.uuid4()),
            action="START",
            action_note="إجراء موثق",
        )
        started = services.advance(**args)
        replay = services.advance(**args)
        self.assertEqual(started["revision"], replay["revision"])
        self.assertFalse(replay["created"])
        with self.assertRaises(cases.CaseConflict):
            services.advance(**{**args, "action_note": "محاولة تبديل الإجراء"})
        original = services._recheck

        def revoke(*a, **kw):
            self.report_authority.denied.add("TRIAGE")
            return original(*a, **kw)

        with (
            patch.object(services, "_recheck", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.advance(started, "RESOLVE", verification_note="نتيجة تحقق موثقة")
        self.assertEqual(ReportEvent.objects.count(), 2)


@override_settings(**SETTINGS)
class ReportHTTPTests(ReportFixture, TransactionTestCase):
    def form(self, page):
        return dict(
            action="content_report",
            revision=page.context["result"]["revision"],
            report_proof=hidden(page, "report_proof"),
            request_key=hidden(page, "request_key"),
            selected_target=page.context["reporting"]["targets"][0]["key"],
            reason="BROKEN_MEDIA",
            description="<script>test</script> مشكلة خاصة",
            evidence_note="PRIVATE REQUESTER EVIDENCE",
        )

    def staff_client(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        response = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-credential-with-32-characters"},
            page,
        )
        self.assertEqual(response.status_code, 303)
        return client, client.get("/casework/staff/")

    def test_native_requester_report_receipt_staff_triage_and_verified_close(self):
        client = self.client_for()
        page = client.get("/casework/status/")
        fields = self.form(page)
        before = list(CaseEvent.objects.values())
        response = post(client, "/casework/status/", fields, page)
        self.assertEqual(response.status_code, 303, response.content)
        receipt = client.get("/casework/status/")
        self.assertContains(receipt, "تأكيد الاستلام ليس إصلاحًا")
        self.assertNotContains(receipt, "PRIVATE REQUESTER EVIDENCE")
        staff, login_page = self.staff_client()
        desk = post(
            staff,
            "/casework/staff/",
            {"action": "reports_open", "case_ref": self.a["public_ref"]},
            login_page,
        )
        self.assertEqual(desk.status_code, 200, desk.content)
        self.assertContains(desk, "&lt;script&gt;test&lt;/script&gt;")
        for action in ("START", "RESOLVE"):
            desk = post(
                staff,
                "/casework/staff/",
                dict(
                    action="report_advance",
                    case_ref=self.a["public_ref"],
                    report_id=hidden(desk, "report_id"),
                    report_revision=hidden(desk, "report_revision"),
                    request_key=hidden(desk, "request_key"),
                    transition=action,
                    action_note="PRIVATE STAFF ACTION",
                    verification_note="PRIVATE VERIFIED" if action == "RESOLVE" else "",
                    related_report_id="",
                ),
                desk,
            )
            self.assertEqual(desk.status_code, 200, desk.content)
        final = client.get("/casework/status/")
        self.assertContains(final, "أغلق بعد تسجيل الإجراء والتحقق")
        self.assertNotContains(final, "PRIVATE STAFF ACTION")
        self.assertNotContains(final, "PRIVATE VERIFIED")
        self.assertEqual(before, list(CaseEvent.objects.values()))
        self.assertEqual(ReportEvent.objects.count(), 3)

    def test_csrf_forged_fields_cross_case_and_anonymous_access_fail_closed(self):
        client = self.client_for()
        page = client.get("/casework/status/")
        fields = self.form(page)
        self.assertEqual(client.post("/casework/status/", fields).status_code, 403)
        self.assertEqual(
            post(
                client, "/casework/status/", {**fields, "case_ref": self.a["public_ref"]}, page
            ).status_code,
            400,
        )
        other = self.intake("http-report-other")
        other_client = self.client_for(other["token"])
        other_page = other_client.get("/casework/status/")
        conflict = post(other_client, "/casework/status/", fields, other_page)
        self.assertEqual(conflict.status_code, 409, conflict.content)
        self.assertNotContains(conflict, "PRIVATE REQUESTER EVIDENCE", status_code=409)
        anonymous = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        locked = anonymous.get("/casework/status/")
        self.assertEqual(post(anonymous, "/casework/status/", fields, locked).status_code, 404)
        self.assertEqual(ContentReport.objects.count(), 0)

    def test_old_form_after_followup_does_not_create_report_and_preserves_authored_note(self):
        client = self.client_for()
        page = client.get("/casework/status/")
        fields = self.form(page)
        cases.add_followup(
            token=self.a["token"],
            text="وقائع أحدث",
            expected_revision=fields["revision"],
            synthetic_fixtures_only=True,
        )
        conflict = post(client, "/casework/status/", fields, page)
        self.assertEqual(conflict.status_code, 409, conflict.content)
        self.assertEqual(ContentReport.objects.count(), 0)
        self.assertEqual(conflict.context["report_evidence"], "PRIVATE REQUESTER EVIDENCE")
        self.assertEqual(conflict.context["reporting"]["targets"], [])


@override_settings(
    **{
        **RESEARCH_SETTINGS,
        "FATWA_CONTENT_REPORTS_ENABLED": True,
        "ROOT_URLCONF": "config.campaign_urls",
    }
)
class StaffSourceReportTests(ResearchFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        authority = FixtureAuthority(
            self.receipt["public_ref"], "synthetic-publication-directory", "editor"
        )
        self.authority = VersionedKnowledgeAuthority(self.receipt["public_ref"])
        configured = override_settings(
            FATWA_CONTENT_REPORTS_AUTHORITY=authority,
            FATWA_KNOWLEDGE_LINKS_AUTHORITY=self.authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def prepared(self, kind="PUBLICATION", target=None):
        target = target or (
            self.edition["id"] if kind == "PUBLICATION" else self.transcript["link_id"]
        )
        return services.prepare_staff_target(**self.common, target_kind=kind, target_id=target)

    def submit(self, prepared, **changes):
        args = dict(
            **self.common,
            target_kind=prepared["target"]["kind"],
            target_id=prepared["target"]["identifier"],
            selected_target=prepared["key"],
            expected_revision=prepared["case_revision"],
            expected_evidence_version=prepared["evidence_version"],
            request_key=str(uuid.uuid4()),
            reason="CONTENT_ERROR",
            description="ملاحظة تحريرية بشرية",
        )
        return services.submit_staff(**{**args, **changes})

    def test_published_edition_and_transcript_readers_supply_exact_pins_without_copied_text(self):
        for kind in ("PUBLICATION", "TRANSCRIPT"):
            prepared = self.prepared(kind)
            saved = self.submit(prepared)
            row = ContentReport.objects.get(pk=saved["id"])
            self.assertEqual(row.target, prepared["target"])
            self.assertNotIn("PRIVATE ANSWER", json.dumps(row.target))
            self.assertNotIn(self.transcript_text, json.dumps(row.target, ensure_ascii=False))
        self.assertEqual(ContentReport.objects.count(), 2)

    def test_superseded_withdrawn_and_forged_edition_are_rejected(self):
        old = self.prepared()
        latest = self.new_publication()
        with self.assertRaises(cases.CaseConflict):
            self.submit(old)
        selected = self.prepared(target=latest["id"])
        with self.assertRaises(cases.CaseConflict):
            self.submit(selected, selected_target=old["key"])
        publication.act(
            **{**self.common, "subject_id": "publisher"}, edition_id=latest["id"], action="WITHDRAW"
        )
        with self.assertRaises(cases.CaseConflict):
            self.submit(selected)
        self.assertEqual(ContentReport.objects.count(), 0)

    def test_current_transcript_permissions_and_reporting_grant_both_required(self):
        selected = self.prepared("TRANSCRIPT")
        self.rights.denied.add(("TRANSCRIPT", "READ_TEXT"))
        with self.assertRaises(cases.CaseConflict):
            self.submit(selected)
        self.rights.denied.clear()
        self.authority.allow_open = False
        with self.assertRaises(cases.CaseConflict):
            self.submit(selected)
        self.authority.allow_open = True
        with (
            override_settings(FATWA_CONTENT_REPORTS_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.submit(selected)
        self.assertEqual(ContentReport.objects.count(), 0)

    def test_native_staff_prepare_submit_and_review_both_existing_source_readers(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        login = client.get("/casework/staff/login/")
        response = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            login,
        )
        self.assertEqual(response.status_code, 303)
        page = client.get("/casework/staff/")
        for kind, target in (
            ("PUBLICATION", self.edition["id"]),
            ("TRANSCRIPT", self.transcript["link_id"]),
        ):
            page = post(
                client,
                "/casework/staff/",
                dict(
                    action="report_prepare",
                    case_ref=self.receipt["public_ref"],
                    target_kind=kind,
                    target_id=target,
                ),
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            fields = {
                name: hidden(page, name)
                for name in (
                    "target_kind",
                    "target_id",
                    "selected_target",
                    "revision",
                    "evidence_version",
                    "request_key",
                )
            }
            page = post(
                client,
                "/casework/staff/",
                {
                    **fields,
                    "action": "report_submit",
                    "case_ref": self.receipt["public_ref"],
                    "reason": "CONTENT_ERROR",
                    "description": "ملاحظة على نسخة المصدر المحددة",
                    "evidence_note": "",
                },
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, "استُلم البلاغ للمراجعة")
        self.assertEqual(ContentReport.objects.count(), 2)
