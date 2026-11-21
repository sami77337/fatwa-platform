"""Real campaign login/CSRF/forms and transactional final rendering, not API wrappers."""

import re
from html import unescape
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.casework.models import AnswerRevision, CaseEvent
from tests.casework.test_http import hidden, post

from . import views
from .models import SearchDocument, SearchGeneration
from .test_support import FEATURES, SearchFixture


@override_settings(**FEATURES)
class CanonicalSearchHTTPTests(SearchFixture, TransactionTestCase):
    def login(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        response = post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        self.assertEqual(response.status_code, 303, response.content)
        return client, client.get("/casework/staff/")

    def submit(self, action, response, *, client=None, case_ref=None, **fields):
        return post(
            client or self.client,
            "/casework/staff/",
            {"action": action, "case_ref": case_ref or self.receipt["public_ref"], **fields},
            response,
        )

    def open(self):
        self.client, page = self.login()
        page = self.submit("cs_open", page)
        self.assertEqual(page.status_code, 200, page.content)
        return page

    def indexed(self):
        page = self.open()
        page = self.submit("cs_rebuild", page, state=hidden(page, "state"))
        self.assertEqual(page.status_code, 200, page.content)
        return page

    def query(self, page, value="المعاملات", mode="FTS"):
        return self.submit(
            "cs_search", page, query=value, mode=mode, kind="ALL", page="1", scope="CASE"
        )

    def result_state(self, page):
        match = re.search(
            r'value="cs_source".*?name="state" value="([^"]+)"', page.content.decode(), re.S
        )
        self.assertIsNotNone(match)
        return unescape(match.group(1))

    def test_native_index_search_literal_fuzzy_and_exact_original_open(self):
        before = CaseEvent.objects.count()
        page = self.indexed()
        found = self.query(page)
        self.assertEqual(found.status_code, 200, found.content)
        self.assertContains(found, "1 نتيجة متاحة")
        self.assertIn("no-store", found["Cache-Control"])
        opened = self.submit("cs_source", found, state=self.result_state(found))
        self.assertEqual(opened.status_code, 200, opened.content)
        self.assertContains(opened, self.question)
        literal = self.query(opened, "المعاملات", "LITERAL")
        self.assertContains(literal, "0 نتيجة متاحة")
        fuzzy = self.query(literal, "المعاملاتت", "FUZZY")
        self.assertContains(fuzzy, "1 نتيجة متاحة")
        self.assertContains(fuzzy, "تقريب كتابي اختير صراحة")
        self.assertEqual(CaseEvent.objects.count(), before)

    def test_csrf_unknown_fields_and_unassigned_case_are_denied(self):
        page = self.open()
        missing_csrf = self.client.post(
            "/casework/staff/", {"action": "cs_open", "case_ref": self.receipt["public_ref"]}
        )
        self.assertEqual(missing_csrf.status_code, 403)
        extra = self.submit("cs_open", page, role="MUFTI")
        self.assertEqual(extra.status_code, 400)
        other = self.new_case("سؤال آخر خاص ذو علامة سرية")
        denied = self.submit("cs_open", page, case_ref=other["public_ref"])
        self.assertEqual(denied.status_code, 403)
        self.assertNotContains(denied, "علامة سرية", status_code=403)

    def test_exact_result_form_is_browser_bound_even_for_same_principal(self):
        page = self.query(self.indexed())
        token = self.result_state(page)
        other_client, other_page = self.login()
        denied = self.submit("cs_source", other_page, client=other_client, state=token)
        self.assertEqual(denied.status_code, 400)
        self.assertNotContains(denied, self.question, status_code=400)

    def test_late_render_grant_revocation_never_returns_old_search_html(self):
        page = self.indexed()
        original = views.render

        def render_then_revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.authority.denied.add("SEARCH")
            return response

        with patch.object(views, "render", side_effect=render_then_revoke):
            denied = self.query(page)
        self.assertEqual(denied.status_code, 409)
        self.assertNotContains(denied, "المُعاملاتِ", status_code=409)

    def test_late_render_canonical_edit_rolls_back_and_rejects_mixed_snapshot(self):
        page = self.indexed()
        original = views.render

        def render_then_edit(*args, **kwargs):
            response = original(*args, **kwargs)
            self.answer("تعديل بشري حدث أثناء العرض الاصطناعي")
            return response

        before = CaseEvent.objects.count()
        with patch.object(views, "render", side_effect=render_then_edit):
            denied = self.query(page)
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(CaseEvent.objects.count(), before)
        self.assertFalse(AnswerRevision.objects.exists())

    def test_native_rebuild_and_its_response_are_atomic_under_late_denial(self):
        page = self.open()
        original = views.render

        def render_then_revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.authority.denied.add("VIEW")
            return response

        with patch.object(views, "render", side_effect=render_then_revoke):
            denied = self.submit("cs_rebuild", page, state=hidden(page, "state"))
        self.assertEqual(denied.status_code, 409)
        self.assertFalse(SearchGeneration.objects.exists())
        self.assertFalse(SearchDocument.objects.exists())
