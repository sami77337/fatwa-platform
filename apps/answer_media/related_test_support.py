"""Actual canonical cases and search generations for the independent editor panel."""

import re
from html import unescape

from django.test import Client

from apps.canonical_search.test_support import FEATURES as SEARCH_FEATURES
from apps.canonical_search.test_support import SearchFixture
from tests.casework.test_http import post

FEATURES = {
    **SEARCH_FEATURES,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED": True,
    "FATWA_ANSWER_LINKS_ENABLED": True,
    "FATWA_ANSWER_RELATED_ENABLED": True,
}
CREDENTIAL = "synthetic-editor-credential-32-characters"


def fields(response, action, index=0):
    forms = re.findall(r"<form\b[^>]*>(.*?)</form>", response.content.decode(), re.S)
    selected = [form for form in forms if f'name="action" value="{action}"' in form][index]
    return {
        name: unescape(value)
        for name, value in re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', selected)
    }


class RelatedFixture(SearchFixture):
    def setUp(self):
        super().setUp()
        self.answer("جواب بشري محفوظ عن المُعاملات المالية")
        self.build()

    def login_client(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1")
        login = client.get("/casework/staff/login/")
        result = post(client, "/casework/staff/login/", {"credential": CREDENTIAL}, login)
        self.assertEqual(result.status_code, 303, result.content)
        return client, client.get("/casework/staff/")

    def editor(self):
        self.client, page = self.login_client()
        result = post(
            self.client,
            "/casework/staff/",
            {"action": "answer_media", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def panel(self, page, action="search", **changes):
        key = "answer_media_related_" + action
        values = fields(page, key)
        if action == "search":
            values.update(query="المعاملات المالية", mode="FTS", scope="CASE")
        values.update(changes)
        return post(self.client, "/casework/staff/", values, page)
