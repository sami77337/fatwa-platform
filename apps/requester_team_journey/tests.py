"""Focused composition contracts: no service implementation is replaced in tests."""
import secrets

from django.test import Client, TransactionTestCase, override_settings
from django.urls import resolve

from apps.casework import services as cases
from apps.casework.models import Case
from apps.requester_access_review import services as reviews
from apps.requester_access_review.models import AccessReview
from tests.casework.test_http import WEB_SETTINGS, Directory, hidden, post

from .settings import TEMPLATES
from .views import PANEL_COOKIE, STAFF

SETTINGS = {**WEB_SETTINGS, "ROOT_URLCONF": "apps.requester_team_journey.urls", "TEMPLATES": TEMPLATES}
STATUS = "/casework/status/"


@override_settings(**SETTINGS)
class RequesterTeamJourneyTests(TransactionTestCase):
    def setUp(self):
        self.directory = Directory()
        self.identity = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        self.identity.enable()
        self.addCleanup(self.identity.disable)
        self.staff = self.browser()
        self.requester = self.browser()

    def browser(self):
        return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def case(self):
        key = secrets.token_hex(16)
        result = cases.intake_case(original_question="سؤال اصطناعي للرحلة الموحدة", source_event_id=key,
                                   requester_id="synthetic-" + key, idempotency_key=key,
                                   synthetic_fixtures_only=True)
        return Case.objects.get(pk=result["case_id"]), result["token"]

    def login(self, *refs):
        self.directory.grant(*refs)
        page = self.staff.get(STAFF + "login/")
        self.assertEqual(post(self.staff, STAFF + "login/", {"credential": self.directory.credential}, page).status_code, 303)
        return self.staff.get(STAFF)

    def test_requester_review_team_queue_and_recovery_are_one_connected_profile(self):
        case, token = self.case()
        page = self.requester.get(STATUS)
        self.assertEqual(post(self.requester, STATUS, {"action": "unlock", "token": token}, page).status_code, 303)
        page = self.requester.get(STATUS)
        self.assertEqual(post(self.requester, STATUS, {"action": "request_access_review", "reason": "EXPOSED",
            "review_proof": hidden(page, "review_proof")}, page).status_code, 303)
        page = self.login(case.public_ref)
        self.assertContains(page, 'id="queue-heading"')
        self.assertContains(page, "طلبات مراجعة الوصول الخاص")
        page = post(self.staff, STAFF, {"action": "access_queue"}, page)
        self.assertContains(page, "أخشى أن رمز الوصول انكشف لشخص آخر")
        self.assertContains(page, "العودة إلى مساحة القضايا")
        review = AccessReview.objects.get()
        response = post(self.staff, STAFF, {"action": "access_acknowledge", "review_id": str(review.pk), "revision": 1}, page)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.cookies[PANEL_COOKIE].value, "access")
        page = self.staff.get(STAFF)
        self.assertContains(page, "الفريق يتابع التحقق الموثوق")
        page = post(self.staff, STAFF, {"action": "open", "case_ref": case.public_ref}, page)
        self.assertContains(page, 'id="selected-reference"')
        self.assertContains(page, 'id="history"')
        self.assertEqual(page.cookies[PANEL_COOKIE].value, "cases")
        with override_settings(FATWA_CASEWORK_RECOVERY_RESOLVER=lambda *args: case.requester_id):
            rotated = post(self.staff, STAFF, {"action": "rotate", "case_ref": case.public_ref}, page)
        self.assertEqual(rotated.status_code, 200)
        replacement = rotated.context["access"]["token"]
        self.assertNotContains(self.requester.get(STATUS), case.public_ref)
        queue = post(self.staff, STAFF, {"action": "access_queue"}, rotated)
        self.assertContains(queue, "إغلاق الطلب بعد إبطال الرمز السابق")
        self.assertEqual(post(self.staff, STAFF, {"action": "access_close", "review_id": str(review.pk), "revision": 2}, queue).status_code, 303)
        final = self.staff.get(STAFF)
        self.assertContains(final, "لا توجد طلبات مفتوحة")
        response = post(self.staff, STAFF, {"action": "journey_cases"}, final)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.cookies[PANEL_COOKIE].value, "cases")
        self.assertContains(self.staff.get(STAFF), 'id="queue-heading"')
        page = self.requester.get(STATUS)
        self.assertEqual(post(self.requester, STATUS, {"action": "unlock", "token": replacement}, page).status_code, 303)
        self.assertContains(self.requester.get(STATUS), "أُغلق الطلب بعد إبطال الرمز السابق")

    def test_team_clarification_guard_is_not_bypassed_by_dispatcher(self):
        case, _ = self.case()
        page = self.login(case.public_ref)
        page = post(self.staff, STAFF, {"action": "open", "case_ref": case.public_ref}, page)
        page = post(self.staff, STAFF, {"action": "clarify", "case_ref": case.public_ref,
            "text": "استيضاح اصطناعي", "revision": 1, "evidence_version": 1}, page)
        self.assertEqual(page.status_code, 200)
        response = post(self.staff, STAFF, {"action": "draft", "case_ref": case.public_ref,
            "text": "محاولة حفظ قبل التعقيب", "revision": 2, "evidence_version": 1}, page)
        self.assertEqual(response.status_code, 409)
        case.refresh_from_db()
        self.assertEqual(case.stage, "NEEDS_CLARIFICATION")
        self.assertEqual(case.answers.count(), 0)
        self.assertContains(response, "نص المحاولة غير المحفوظة", status_code=409)

    def test_panel_cookie_grants_no_identity_scope_or_csrf_privileges(self):
        alpha, _ = self.case()
        beta, beta_token = self.case()
        reviews.request_review(token=beta_token, reason="EXPOSED", expected_case_ref=beta.public_ref,
                               synthetic_fixtures_only=True)
        guest = self.browser()
        for value in ("access", "cases", "MUFTI", beta.public_ref):
            guest.cookies[PANEL_COOKIE] = value
            response = guest.get(STAFF)
            self.assertEqual(response.status_code, 403)
            self.assertNotContains(response, beta.public_ref, status_code=403)
        page = self.login(alpha.public_ref)
        self.staff.cookies[PANEL_COOKIE] = "access"
        queue = self.staff.get(STAFF)
        self.assertNotContains(queue, beta.public_ref)
        review = AccessReview.objects.get(case=beta)
        self.assertEqual(post(self.staff, STAFF, {"action": "access_acknowledge", "review_id": str(review.pk), "revision": 1}, queue).status_code, 409)
        self.assertEqual(post(self.staff, STAFF, {"action": "open", "case_ref": beta.public_ref}, queue).status_code, 403)
        self.assertEqual(self.staff.post(STAFF, {"action": "journey_cases"}).status_code, 403)
        self.assertEqual(post(self.staff, STAFF, {"action": "journey_cases", "role": "MUFTI"}, page).status_code, 400)

    def test_shared_guards_route_selection_and_overlay_inheritance(self):
        case, _ = self.case()
        page = self.login(case.public_ref)
        self.assertContains(page, "مساحة الشيخ والفريق")
        self.assertContains(page, "عرض القضايا")
        self.assertContains(page, "طلبات مراجعة الوصول الخاص", count=1)
        self.assertIn("no-store", page["Cache-Control"])
        self.assertIn("noindex", page["X-Robots-Tag"])
        self.assertEqual(resolve(STATUS).func.__module__, "apps.requester_access_review.views")
        self.assertEqual(resolve("/casework/").func.__module__, "apps.casework_web.requester_intake")
        self.assertEqual(resolve("/casework/casework.css").func.__module__, "apps.team_workspace.views")
        self.assertEqual(self.staff.get(STAFF + "?panel=access").status_code, 400)
        self.assertEqual(self.staff.get(STAFF, REMOTE_ADDR="192.0.2.9").status_code, 403)
        self.assertEqual(self.staff.head(STAFF).content, b"")
        with override_settings(FATWA_CASEWORK_WEB_ENABLED=False):
            self.assertEqual(self.staff.get(STAFF).status_code, 503)
