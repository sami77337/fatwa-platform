"""Focused isolation and state compatibility for #219 + #212 + requester access."""

from dataclasses import replace
from urllib.parse import urlencode

from django.test import TransactionTestCase, override_settings

from apps.requester_access_review.models import AccessReview
from apps.requester_team_journey.views import PANEL_COOKIE
from tests.casework import test_http as http
from tests.casework import test_requester_workspace as requester
from tests.casework.test_http import hidden, post

from .models import SeenUpdate

ROOT = "config.campaign_urls"
STAFF = "/casework/staff/"
STATUS = "/casework/status/"


@override_settings(**{**requester.WORKSPACE_SETTINGS, "ROOT_URLCONF": ROOT})
class CompatibilityTests(TransactionTestCase):
    browser = requester.RequesterWorkspaceTests.browser
    intake = requester.RequesterWorkspaceTests.intake
    followup = requester.RequesterWorkspaceTests.followup
    login = http.CaseworkHTTPTests.login
    open_case = http.CaseworkHTTPTests.open_case

    def setUp(self):
        self.directory = http.Directory()
        setting = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        setting.enable()
        self.addCleanup(setting.disable)
        self.client = self.browser()

    def start(self):
        requester_browser = self.client
        case, token, *_ = self.intake()
        self.directory.grant(case.public_ref)
        self.client = self.browser()
        return case, token, requester_browser, self.login()

    def inbox(self, team):
        page = post(self.client, STAFF, {
            "action": "updates_filter", "state": "unread", "kind": "all", "page": "1",
        }, team)
        self.assertEqual(page.status_code, 200)
        return page

    def seen(self, page, row=None):
        row = row or page.context["updates"][0]
        return post(self.client, STAFF, {
            "action": "updates_seen", "case_ref": row["case_ref"],
            "sequence": row["sequence"], "proof": row["proof"],
        }, page)

    def draft(self, case, page, text="PRIVATE DRAFT"):
        return post(self.client, STAFF, {"action": "draft", "case_ref": case.public_ref,
            "revision": hidden(page, "revision"),
            "evidence_version": hidden(page, "evidence_version"), "text": text}, page)

    def case_state(self, case):
        case.refresh_from_db()
        return (case.stage, case.revision, case.evidence_version, case.answer_revision,
                case.approved_answer_id, list(case.events.values_list("sequence", "action")))

    def test_team_landing_and_access_queue_survive_inbox_composition(self):
        case, token, requester_browser, team = self.start()
        self.assertContains(team, 'id="queue-state"')
        self.assertContains(team, "طلبات مراجعة الوصول")
        requester_page = requester_browser.get(STATUS)
        response = post(requester_browser, STATUS, {
            "action": "request_access_review", "reason": "LOST_COPY",
            "review_proof": hidden(requester_page, "review_proof"),
        }, requester_page)
        self.assertEqual(response.status_code, 303)
        review = AccessReview.objects.get()
        before = self.case_state(case)
        updates = self.inbox(team)
        self.assertNotContains(updates, case.source.original_question)
        self.assertNotContains(updates, token)
        self.assertEqual(self.seen(updates).status_code, 200)
        self.assertEqual(self.case_state(case), before)
        review.refresh_from_db()
        self.assertEqual(review.state, "REQUESTED")
        queue = post(self.client, STAFF, {"action": "access_queue"}, updates)
        self.assertContains(queue, "بدء متابعة التحقق")
        editor = self.open_case(case, queue)
        self.assertContains(editor, 'id="answer-text"')
        self.assertContains(editor, 'id="queue-state"')

    def test_pending_clarification_cannot_be_bypassed_by_inbox_case_dispatch(self):
        case, _, _, team = self.start()
        editor = self.open_case(case, team)
        waiting = post(self.client, STAFF, {
            "action": "clarify", "case_ref": case.public_ref, "text": "وضح الواقعة",
            "revision": hidden(editor, "revision"),
            "evidence_version": hidden(editor, "evidence_version"),
        }, editor)
        self.assertEqual(waiting.status_code, 200)
        before = self.case_state(case)
        # A forged native form must reach #212's waiting guard, not the legacy editor.
        refused = self.draft(case, waiting)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.case_state(case), before)
        self.assertEqual(case.answers.count(), 0)

    def test_marking_new_evidence_seen_does_not_revalidate_stale_team_answer(self):
        case, _, requester_browser, team = self.start()
        old_editor = self.open_case(case, team)
        requester_page = requester_browser.get(STATUS)
        self.assertEqual(self.followup(requester_page, "PRIVATE FOLLOWUP", requester_browser).status_code, 303)
        before = self.case_state(case)
        updates = self.inbox(team)
        self.assertEqual(updates.context["updates"][0]["kind"], "FOLLOWUP")
        self.assertNotContains(updates, "PRIVATE FOLLOWUP")
        self.assertEqual(self.seen(updates).status_code, 200)
        self.assertEqual(self.case_state(case), before)
        refused = self.draft(case, old_editor)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(case.answers.count(), 0)
        self.assertEqual(self.case_state(case), before)

    def test_requester_cross_case_and_revoked_staff_cannot_read_or_acknowledge(self):
        case, _, requester_browser, team = self.start()
        other, _, *_ = self.intake(self.browser(), "OUTSIDE SCOPE QUESTION")
        updates = self.inbox(team)
        self.assertNotContains(updates, other.public_ref)
        self.assertNotContains(updates, "OUTSIDE SCOPE QUESTION")
        requester_page = requester_browser.get(STATUS)
        denied = post(requester_browser, STAFF, {
            "action": "updates_filter", "state": "unread", "kind": "all", "page": "1",
        }, requester_page)
        self.assertEqual(denied.status_code, 403)
        row = updates.context["updates"][0]
        denied = post(requester_browser, STAFF, {
            "action": "updates_seen", "case_ref": row["case_ref"],
            "sequence": row["sequence"], "proof": row["proof"],
        }, requester_page)
        self.assertEqual(denied.status_code, 403)
        before = self.case_state(case)
        self.directory.current = replace(self.directory.current, auth_epoch="revoked")
        self.assertEqual(self.seen(updates).status_code, 403)
        self.assertEqual(SeenUpdate.objects.count(), 0)
        self.assertEqual(self.case_state(case), before)

    def test_inbox_entry_stays_csrf_protected_and_rejects_implicit_grants(self):
        _, _, _, team = self.start()
        filters = {"action": "updates_filter", "state": "unread", "kind": "all", "page": "1"}
        self.assertEqual(self.client.post(STAFF, filters).status_code, 403)
        self.assertEqual(post(self.client, STAFF, {
            **filters, "role": "MUFTI",
        }, team).status_code, 400)
        duplicate = urlencode({**filters, "action": ["open", "updates_filter"],
                               "csrfmiddlewaretoken": hidden(team, "csrfmiddlewaretoken")},
                              doseq=True)
        response = self.client.post(STAFF, duplicate,
                                    content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SeenUpdate.objects.count(), 0)

    def test_seen_marker_preserves_approval_and_requester_projection(self):
        case, _, requester_browser, team = self.start()
        editor = self.open_case(case, team)
        editor = self.draft(case, editor, text="PRIVATE APPROVED ANSWER")
        approved = post(self.client, STAFF, {
            "action": "approve", "case_ref": case.public_ref,
            "revision": hidden(editor, "revision"),
            "evidence_version": hidden(editor, "evidence_version"),
            "answer_id": hidden(editor, "answer_id"), "note": "PRIVATE APPROVAL NOTE",
        }, editor)
        self.assertEqual(approved.status_code, 200)
        before = self.case_state(case)
        self.assertEqual(before[0], "ANSWERED")
        updates = self.inbox(approved)
        self.assertTrue(updates.context["updates"][0]["historical"])
        for private in ("PRIVATE APPROVED ANSWER", "PRIVATE APPROVAL NOTE"):
            self.assertNotContains(updates, private)
        self.assertEqual(self.seen(updates).status_code, 200)
        self.assertEqual(self.case_state(case), before)
        status = requester_browser.get(STATUS)
        self.assertContains(status, "اكتملت مراجعة الجواب")
        for private in ("PRIVATE APPROVED ANSWER", "PRIVATE APPROVAL NOTE", "الجواب متاح"):
            self.assertNotContains(status, private)

    def test_panel_cookie_never_restores_requester_or_revoked_staff_authority(self):
        case, _, requester_browser, team = self.start()
        self.inbox(team)
        before = self.case_state(case)
        self.directory.current = replace(self.directory.current, auth_epoch="revoked")
        for panel in ("updates", "access", "cases", "delivery", "MUFTI"):
            for browser in (requester_browser, self.client):
                with self.subTest(panel=panel, browser="requester" if browser is requester_browser else "staff"):
                    browser.cookies[PANEL_COOKIE] = panel
                    denied = browser.get(STAFF)
                    self.assertEqual(denied.status_code, 403)
                    self.assertIn("no-store", denied["Cache-Control"])
                    self.assertNotContains(denied, case.public_ref, status_code=403)
        self.assertEqual(SeenUpdate.objects.count(), 0)
        self.assertEqual(self.case_state(case), before)
