"""Connected, guarded FAST5 pages retain the existing FAST4 entry points."""

from html.parser import HTMLParser

from django.test import SimpleTestCase
from django.urls import reverse


class Fast5Navigation(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inside = False
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "أدوات FAST5":
            self.inside = True
        if self.inside and tag == "a":
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "nav":
            self.inside = False


class Fast5IntegrationTests(SimpleTestCase):
    def test_shared_navigation_connects_fast5_and_existing_fast4(self):
        routes = [
            reverse(f"{name}:index")
            for name in (
                "editorial_dashboard",
                "workflow_rehearsal",
                "research_bridge",
                "permission_lab",
            )
        ]
        for route in routes + [
            reverse(f"editorial_{name}:index") for name in ("search", "followup", "export")
        ]:
            with self.subTest(route=route):
                response = self.client.get(route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(Fast5Navigation(response.content.decode()).links, routes)
                self.assertContains(response, 'lang="ar" dir="rtl"')
                self.assertEqual(response["Cache-Control"], "no-store")

    def test_rehearsal_links_to_exact_research_occurrence(self):
        response = self.client.get(
            reverse("workflow_rehearsal:detail", args=["intake-7"]),
            HTTP_HOST="localhost",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertContains(response, 'href="/dev/research-bridge/intake-7#reference-1"')

    def test_three_new_routes_keep_head_private_and_empty(self):
        for name in ("workflow_rehearsal", "research_bridge", "permission_lab"):
            with self.subTest(name=name):
                response = self.client.head(
                    reverse(f"{name}:index"), HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"")
                self.assertEqual(response["Cache-Control"], "no-store")
