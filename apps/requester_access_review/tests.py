"""Synthetic access-review journeys against real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from django.db import close_old_connections, connections
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.models import RequesterTrackingToken
from tests.casework.test_http import Directory, hidden, post
from tests.casework.test_requester_workspace import WORKSPACE_SETTINGS

from . import services
from .models import AccessReview

SETTINGS = {**WORKSPACE_SETTINGS, "ROOT_URLCONF": "apps.requester_access_review.urls"}
URL = "/casework/status/"
STAFF = "/casework/staff/"


@override_settings(**SETTINGS)
class AccessReviewTests(TransactionTestCase):
    def setUp(self):
        self.directory = Directory()
        self.identity = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        self.identity.enable()
        self.addCleanup(self.identity.disable)
        self.requester = self.browser()
        self.staff = self.browser()

    def browser(self):
        return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def intake(self, requester=None):
        requester = requester or self.requester
        page = requester.get("/casework/")
        request_id = hidden(page, "request_id")
        response = post(requester, "/casework/", {
            "request_id": request_id, "confirmation": hidden(page, "confirmation"),
            "question": "سؤال اصطناعي خاص لا يظهر في طلب مراجعة الوصول.",
        }, page)
        self.assertEqual(response.status_code, 200)
        case = Case.objects.get(idempotency_key=request_id)
        return case, response.context["result"]["token"]

    def request_help(self, page=None, requester=None, reason="LOST_COPY"):
        requester = requester or self.requester
        page = page or requester.get(URL)
        return post(requester, URL, {"action": "request_access_review", "reason": reason,
                                     "review_proof": hidden(page, "review_proof")}, page)

    def login(self, *refs):
        self.directory.grant(*refs)
        page = self.staff.get(STAFF + "login/")
        response = post(self.staff, STAFF + "login/", {"credential": self.directory.credential}, page)
        self.assertEqual(response.status_code, 303)
        return self.staff.get(STAFF)

    def common(self, case):
        return {"case_id": str(case.pk), "provider": self.directory,
                "subject_id": self.directory.current.subject_id, "synthetic_fixtures_only": True}

    def advance(self, review, action, page=None, revision=None):
        return post(self.staff, STAFF, {"action": "access_" + action,
            "review_id": str(review.pk), "revision": revision or review.revision,
        }, page or self.staff.get(STAFF))

    def test_request_queue_trusted_rotation_and_resolution_end_to_end(self):
        case, token = self.intake()
        original_events = list(case.events.values_list("sequence", "action"))
        page = self.requester.get(URL)
        self.assertContains(page, "حفظ طلب مراجعة الوصول")
        self.assertEqual(self.request_help(page).status_code, 303)
        self.assertEqual(self.request_help(page).status_code, 303)
        self.assertEqual(AccessReview.objects.count(), 1)
        review = AccessReview.objects.get()
        self.assertEqual(review.state, "REQUESTED")
        requester_page = self.requester.get(URL)
        self.assertContains(requester_page, "طلب المراجعة محفوظ")
        for value in (token, str(review.pk), review.grant_id, str(case.pk), case.requester_id):
            self.assertNotContains(requester_page, value)
        staff_page = self.login(case.public_ref)
        self.assertContains(staff_page, case.public_ref)
        self.assertNotContains(staff_page, token)
        self.assertNotContains(staff_page, case.source.original_question)
        self.assertEqual(self.advance(review, "acknowledge", staff_page).status_code, 303)
        review.refresh_from_db()
        self.assertEqual(review.revision, 2)
        self.assertEqual(review.acknowledged_by, self.directory.current.subject_id)
        self.assertContains(self.requester.get(URL), "الفريق يتابع التحقق الموثوق")
        self.assertEqual(self.advance(review, "close").status_code, 409)
        self.assertEqual(list(case.events.values_list("sequence", "action")), original_events)
        self.assertEqual(RequesterTrackingToken.objects.filter(case_id=case.tracking_id).count(), 1)

        # Existing staff route still requires the trusted server resolver to rotate.
        page = self.staff.get(STAFF)
        with override_settings(FATWA_CASEWORK_RECOVERY_RESOLVER=None):
            denied = post(self.staff, STAFF, {"action": "rotate", "case_ref": case.public_ref}, page)
            self.assertEqual(denied.status_code, 503)
        self.assertEqual(self.advance(review, "close").status_code, 409)
        with override_settings(FATWA_CASEWORK_RECOVERY_RESOLVER=lambda *args: case.requester_id):
            response = post(self.staff, STAFF, {"action": "rotate", "case_ref": case.public_ref}, page)
        self.assertEqual(response.status_code, 200)
        replacement = response.context["access"]["token"]
        self.assertNotContains(self.requester.get(URL), case.public_ref)
        self.assertEqual(self.advance(review, "close").status_code, 303)
        review.refresh_from_db()
        self.assertEqual(review.state, "CLOSED")
        self.assertEqual(review.closed_by, self.directory.current.subject_id)
        page = self.requester.get(URL)
        self.assertEqual(post(self.requester, URL, {"action": "unlock", "token": replacement}, page).status_code, 303)
        final = self.requester.get(URL)
        self.assertContains(final, "أُغلق الطلب بعد إبطال الرمز السابق")
        self.assertNotContains(final, replacement)
        self.assertNotContains(final, self.directory.current.subject_id)
        self.assertEqual(case.evidence.count(), 1)

    def test_session_required_not_reference_intake_cookie_or_unknown_token(self):
        case, token = self.intake()
        page = self.requester.get(URL)
        guest = self.browser()
        guest.get(URL)
        from apps.casework_web.views import REQUESTER_COOKIE
        guest.cookies[REQUESTER_COOKIE] = self.requester.cookies[REQUESTER_COOKIE].value
        response = post(guest, URL, {"action": "request_access_review", "reason": "EXPOSED",
                                     "review_proof": hidden(page, "review_proof")}, guest.get(URL))
        self.assertEqual(response.status_code, 404)
        for bad in (case.public_ref, "invalid"):
            with self.assertRaises(cases.CaseConflict):
                services.request_review(token=bad, reason="LOST_COPY", expected_case_ref=case.public_ref,
                                        synthetic_fixtures_only=True)
        self.assertEqual(AccessReview.objects.count(), 0)
        # Expired/revoked capability cannot open the request path either.
        self.directory.grant(case.public_ref)
        cases.revoke_access(**self.common(case), requester_id=case.requester_id)
        self.assertEqual(self.request_help(page).status_code, 404)
        self.assertEqual(AccessReview.objects.count(), 0)

    def test_case_scope_role_confusion_and_stale_staff_revision(self):
        alpha, _ = self.intake()
        self.assertEqual(self.request_help().status_code, 303)
        beta_browser = self.browser()
        beta, _ = self.intake(beta_browser)
        self.assertEqual(self.request_help(requester=beta_browser).status_code, 303)
        review = AccessReview.objects.get(case=beta)
        page = self.login(alpha.public_ref)
        self.assertNotContains(page, beta.public_ref)
        self.assertEqual(self.advance(review, "acknowledge", page).status_code, 409)
        alpha_review = AccessReview.objects.get(case=alpha)
        self.assertEqual(self.advance(alpha_review, "acknowledge", page).status_code, 303)
        self.assertEqual(self.advance(alpha_review, "acknowledge", page, revision=1).status_code, 409)
        self.directory.current = replace(self.directory.current, role="ORGANIZER_ADMIN")
        self.assertEqual(self.staff.get(STAFF).status_code, 403)
        review.refresh_from_db()
        self.assertEqual(review.state, "REQUESTED")

    def test_cross_case_stale_form_does_not_create_request_for_new_case(self):
        alpha, _ = self.intake()
        old_page = self.requester.get(URL)
        other = self.browser()
        beta, beta_token = self.intake(other)
        response = post(self.requester, URL, {"action": "unlock", "token": beta_token}, old_page)
        self.assertEqual(response.status_code, 303)
        response = self.request_help(old_page)
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, alpha.public_ref, status_code=409)
        self.assertNotContains(response, beta.public_ref, status_code=409)
        self.assertEqual(AccessReview.objects.count(), 0)

    def test_csrf_exact_shape_headers_and_no_self_service_recovery(self):
        case, token = self.intake()
        page = self.requester.get(URL)
        self.assertEqual(self.requester.post(URL, {"action": "request_access_review"}).status_code, 403)
        self.assertEqual(post(self.requester, URL, {"action": "request_access_review", "reason": "EXPOSED",
            "review_proof": hidden(page, "review_proof"), "role": "MUFTI"}, page).status_code, 400)
        self.assertEqual(self.requester.get(URL + "?token=synthetic").status_code, 400)
        self.assertEqual(self.request_help(page, reason="rotate_now").status_code, 400)
        self.assertEqual(AccessReview.objects.count(), 0)
        self.assertIn("no-store", page["Cache-Control"])
        self.assertIn("noindex", page["X-Robots-Tag"])
        self.assertEqual(self.request_help(reason="EXPOSED").status_code, 303)
        self.assertEqual(cases.requester_status(token, synthetic_fixtures_only=True)["public_ref"], case.public_ref)
        self.assertEqual(RequesterTrackingToken.objects.filter(case_id=case.tracking_id).count(), 1)
        self.assertEqual(case.events.count(), 1)
        with override_settings(FATWA_CASEWORK_WEB_ENABLED=False):
            self.assertEqual(self.requester.get(URL).status_code, 503)

    def test_concurrent_duplicate_requests_keep_one_original_reason(self):
        case, token = self.intake()

        def submit():
            close_old_connections()
            try:
                return services.request_review(token=token, reason="EXPOSED", expected_case_ref=case.public_ref,
                                               synthetic_fixtures_only=True)["created"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sorted(outcomes), [False, True])
        services.request_review(token=token, reason="LOST_COPY", expected_case_ref=case.public_ref,
                                synthetic_fixtures_only=True)
        self.assertEqual(AccessReview.objects.get().reason, "EXPOSED")
        self.assertEqual(case.events.count(), 1)

    def test_rotation_racing_with_request_rechecks_capability_under_core_lock(self):
        case, token = self.intake()
        self.directory.grant(case.public_ref)
        page = self.requester.get(URL)
        original = services.request_review

        def rotate_then_request(**kwargs):
            cases.rotate_access(**self.common(case), requester_id=case.requester_id)
            return original(**kwargs)

        with patch("apps.requester_access_review.views.services.request_review", side_effect=rotate_then_request):
            response = self.request_help(page)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, case.public_ref, status_code=404)
        self.assertEqual(AccessReview.objects.count(), 0)
