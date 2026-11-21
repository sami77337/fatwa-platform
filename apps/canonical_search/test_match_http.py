"""Signed native next/previous forms keep exact text behind current case rights."""

import re
from html import unescape
from html.parser import HTMLParser
from unittest.mock import patch

from django.core import signing
from django.test import TransactionTestCase, override_settings

from apps.casework.models import CaseEvent

from . import test_http, views
from .test_support import FEATURES, SearchFixture


class SourceText(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.depth, self.parts = 0, []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if dict(attrs).get("id") == "canonical-source-text":
            self.depth = 1
        elif self.depth:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def form_state(response, identifier):
    form = re.search(
        rf'<form\b[^>]*\bid="{identifier}"[^>]*>(.*?)</form>', response.content.decode(), re.S
    )
    if form is None:
        raise AssertionError(f"Missing native form: {identifier}")
    return unescape(re.search(r'name="state" value="([^"]+)"', form.group(1)).group(1))


@override_settings(**FEATURES)
class MatchHTTPTests(SearchFixture, TransactionTestCase):
    login = test_http.CanonicalSearchHTTPTests.login
    submit = test_http.CanonicalSearchHTTPTests.submit
    open = test_http.CanonicalSearchHTTPTests.open
    indexed = test_http.CanonicalSearchHTTPTests.indexed
    query = test_http.CanonicalSearchHTTPTests.query
    result_state = test_http.CanonicalSearchHTTPTests.result_state

    def selected_answer(self):
        original = "  المُعاملاتِ ثم المعاملات\r\n<script>private()</script> ثم المُعاملات  "
        self.answer(original)
        page = self.submit(
            "cs_search",
            self.indexed(),
            query="المعاملات",
            mode="FTS",
            kind="ANSWER",
            page="1",
            scope="CASE",
        )
        self.assertEqual(page.status_code, 200, page.content)
        return original, page

    def test_native_next_and_previous_preserve_source_bytes_and_escape_html(self):
        original, found = self.selected_answer()
        before = CaseEvent.objects.count()
        first = self.submit("cs_source", found, state=self.result_state(found))
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual("".join(SourceText(first.content.decode()).parts), original)
        self.assertContains(first, "&lt;script&gt;private()&lt;/script&gt;")
        self.assertNotContains(first, "<script>private()")
        self.assertContains(first, "الموضع 1 من 3")
        self.assertNotContains(first, 'id="canonical-previous-match"')
        second = self.submit("cs_source", first, state=form_state(first, "canonical-next-match"))
        self.assertEqual(second.status_code, 200, second.content)
        self.assertContains(second, "الموضع 2 من 3")
        self.assertEqual("".join(SourceText(second.content.decode()).parts), original)
        third = self.submit("cs_source", second, state=form_state(second, "canonical-next-match"))
        self.assertContains(third, "الموضع 3 من 3")
        self.assertNotContains(third, 'id="canonical-next-match"')
        previous = self.submit(
            "cs_source", third, state=form_state(third, "canonical-previous-match")
        )
        self.assertContains(previous, "الموضع 2 من 3")
        self.assertEqual("".join(SourceText(previous.content.decode()).parts), original)
        self.assertEqual(CaseEvent.objects.count(), before)
        self.assertIn("no-store", previous["Cache-Control"])

    def test_query_mode_and_position_are_signed_and_untrusted_fields_rejected(self):
        _, found = self.selected_answer()
        token = self.result_state(found)
        state = signing.loads(token, salt=views.SALT)
        self.assertEqual(
            (state["query"], state["mode"], state["match_index"]), ("المعاملات", "FTS", 0)
        )
        tampered = self.submit("cs_source", found, state=token + ".")
        self.assertEqual(tampered.status_code, 400)
        extra = self.submit("cs_source", found, state=token, match_index="1")
        self.assertEqual(extra.status_code, 400)
        for change in (
            {"match_index": True},
            {"match_index": 999},
            {"query": "كلمةغيرموجودة"},
            {"mode": "LITERAL", "query": "المُعاملات المالية"},
        ):
            with self.subTest(change=change):
                invalid = signing.dumps({**state, **change}, salt=views.SALT, compress=True)
                response = self.submit("cs_source", found, state=invalid)
                self.assertEqual(response.status_code, 409, response.content)
                self.assertNotContains(response, "private()", status_code=409)

    def test_each_navigation_rechecks_current_search_and_open_access(self):
        _, found = self.selected_answer()
        first = self.submit("cs_source", found, state=self.result_state(found))
        token = form_state(first, "canonical-next-match")
        for permission in ("SEARCH", "OPEN"):
            with self.subTest(permission=permission):
                self.authority.denied.add(permission)
                denied = self.submit("cs_source", first, state=token)
                self.assertEqual(denied.status_code, 409, denied.content)
                self.assertNotContains(denied, "private()", status_code=409)
                self.authority.denied.remove(permission)
        reopened = self.submit("cs_source", first, state=token)
        self.assertContains(reopened, "الموضع 2 من 3")
        self.answer("الجواب الحالي تغير")
        stale = self.submit("cs_source", reopened, state=token)
        self.assertEqual(stale.status_code, 409)
        self.assertNotContains(stale, "private()", status_code=409)

    def test_final_render_revocation_discards_all_highlighted_html(self):
        _, found = self.selected_answer()
        original = views.render

        def revoke(*args, **kwargs):
            response = original(*args, **kwargs)
            self.authority.denied.add("SEARCH")
            return response

        with patch.object(views, "render", side_effect=revoke):
            denied = self.submit("cs_source", found, state=self.result_state(found))
        self.assertEqual(denied.status_code, 409)
        self.assertNotContains(denied, "private()", status_code=409)

    def test_approximate_result_without_literal_span_keeps_the_exact_original(self):
        page = self.query(self.indexed(), "المعاملاتت", "FUZZY")
        opened = self.submit("cs_source", page, state=self.result_state(page))
        self.assertEqual(opened.status_code, 200, opened.content)
        self.assertEqual("".join(SourceText(opened.content.decode()).parts), self.question)
        self.assertContains(opened, "نتيجة تقريبية ولا تتضمن مقطعًا مطابقًا")
        self.assertNotContains(opened, 'id="canonical-active-match"')
