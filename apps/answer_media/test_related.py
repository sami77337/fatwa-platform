"""Native side-panel isolation, exact source pins and late composed-read denial."""

from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.casework.models import AnswerRevision, CaseEvent
from tests.casework.test_http import post

from . import related_views
from .editor_boundary import head
from .models import AnswerPart
from .related_test_support import FEATURES, RelatedFixture, fields


@override_settings(**FEATURES)
class RelatedMaterialHTTPTests(RelatedFixture, TransactionTestCase):
    def state(self):
        return (
            head(self.common["case_id"]),
            CaseEvent.objects.count(),
            AnswerRevision.objects.count(),
            AnswerPart.objects.count(),
        )

    def test_separate_native_panel_search_open_back_preserves_canonical_answer(self):
        before = self.state()
        page = self.editor()
        self.assertContains(page, 'id="answer-related-panel"')
        self.assertContains(page, 'aria-label="مسودة الجواب المستقلة"')
        self.assertContains(page, 'src="/casework/staff/answer-media/related.mjs"')
        self.assertIn("connect-src 'self'", page["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", page["Content-Security-Policy"])
        found = self.panel(page)
        self.assertEqual(found.status_code, 200, found.content)
        self.assertEqual(found["X-Answer-Related-Panel"], "1")
        self.assertContains(found, self.question)
        self.assertNotContains(found, "<textarea")
        self.assertNotContains(found, 'name="answer_file"')
        opened = self.panel(found, "open")
        self.assertEqual(opened.status_code, 200, opened.content)
        self.assertContains(opened, 'id="related-source-text"')
        self.assertContains(opened, self.question)
        back = self.panel(opened, "back")
        self.assertEqual(back.status_code, 200, back.content)
        self.assertContains(back, self.question)
        self.assertEqual(self.state(), before)

    def test_explicit_literal_fuzzy_and_scoped_results_never_include_unscoped_case(self):
        secret = "سؤال خفي عن المعاملات المالية"
        self.new_case(secret)
        page = self.editor()
        literal = self.panel(page, mode="LITERAL")
        self.assertEqual(literal.status_code, 200)
        self.assertNotContains(literal, self.question)
        fuzzy = self.panel(literal, query="المعاملاتت", mode="FUZZY", scope="SCOPED")
        self.assertEqual(fuzzy.status_code, 200, fuzzy.content)
        self.assertContains(fuzzy, self.question)
        self.assertNotContains(fuzzy, secret)

    def test_csrf_unknown_draft_fields_and_different_session_or_case_are_rejected(self):
        page = self.editor()
        values = fields(page, "answer_media_related_search")
        values.update(query="المعاملات", mode="FTS", scope="CASE")
        without = {key: value for key, value in values.items() if key != "csrfmiddlewaretoken"}
        self.assertEqual(self.client.post("/casework/staff/", without).status_code, 403)
        malformed = self.panel(page, text="UNSAVED DRAFT IS NOT A PANEL INPUT")
        self.assertEqual(malformed.status_code, 400)
        other_client, other_page = self.login_client()
        values.pop("csrfmiddlewaretoken")
        copied = post(other_client, "/casework/staff/", values, other_page)
        self.assertEqual(copied.status_code, 400, copied.content)
        other = self.new_case("قضية أخرى غير مخولة")
        denied = self.panel(page, case_ref=other["public_ref"])
        self.assertNotEqual(denied.status_code, 200)
        self.assertNotContains(denied, self.question, status_code=denied.status_code)

    def test_old_editor_pin_and_old_source_selection_do_not_follow_latest_silently(self):
        page = self.editor()
        result = self.panel(page)
        self.answer("جواب بشري جديد يغير نسخة المحرر")
        self.build()
        before = self.state()
        stale_query = self.panel(page)
        stale_source = self.panel(result, "open")
        self.assertEqual(stale_query.status_code, 409)
        self.assertEqual(stale_source.status_code, 409)
        self.assertNotIn(self.question.encode(), stale_source.content)
        self.assertEqual(self.state(), before)

    def test_late_render_source_change_rejects_html_and_rolls_back_real_edit(self):
        page = self.editor()
        before = self.state()
        original = related_views.render

        def changed(*args, **kwargs):
            response = original(*args, **kwargs)
            self.answer("نسخة تغيرت في آخر خطوة من تركيب المعاينة")
            return response

        with patch.object(related_views, "render", side_effect=changed):
            result = self.panel(page)
        self.assertEqual(result.status_code, 409, result.content)
        self.assertNotIn(self.question.encode(), result.content)
        self.assertEqual(self.state(), before)

    def test_late_identity_and_final_policy_callback_cannot_keep_old_panel(self):
        page = self.editor()
        original = related_views.render
        active = self.directory.identities["editor"]

        def revoked(*args, **kwargs):
            response = original(*args, **kwargs)
            self.directory.identities["editor"] = replace(active, active=False)
            return response

        with patch.object(related_views, "render", side_effect=revoked):
            denied = self.panel(page)
        self.assertNotEqual(denied.status_code, 200)
        self.assertNotIn(self.question.encode(), denied.content)
        self.directory.identities["editor"] = active
        rendered = False

        def rendered_response(*args, **kwargs):
            nonlocal rendered
            result = original(*args, **kwargs)
            rendered = True
            return result

        def final_callback(values):
            if rendered:
                settings.FATWA_ANSWER_RELATED_ENABLED = False

        self.authority.hook = final_callback
        try:
            with patch.object(related_views, "render", side_effect=rendered_response):
                denied = self.panel(page)
            self.assertEqual(denied.status_code, 409, denied.content)
            self.assertNotIn(self.question.encode(), denied.content)
        finally:
            settings.FATWA_ANSWER_RELATED_ENABLED = True
            self.authority.hook = None

    def test_optional_panel_closed_and_private_asset_methods_are_bounded(self):
        page = self.editor()
        route = "/casework/staff/answer-media/related.mjs"
        script = self.client.get(route)
        self.assertEqual(script.status_code, 200, script.content)
        self.assertIn("no-store", script["Cache-Control"])
        self.assertIn("text/javascript", script["Content-Type"])
        self.assertEqual(self.client.head(route).content, b"")
        self.assertNotEqual(self.client.post(route).status_code, 200)
        with override_settings(FATWA_ANSWER_RELATED_ENABLED=False):
            denied = self.panel(page)
            self.assertEqual(denied.status_code, 409)
            self.assertEqual(self.client.get(route).status_code, 404)
            editor = self.editor()
            self.assertNotContains(editor, 'id="answer-related-panel"')
            self.assertNotIn("connect-src", editor["Content-Security-Policy"])
