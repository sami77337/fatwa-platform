"""FAST4 routes stay connected on the real guarded synthetic application."""

from html.parser import HTMLParser

from django.test import SimpleTestCase
from django.urls import reverse


class Navigation(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inside = False
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "أدوات FAST4":
            self.inside = True
        if self.inside and tag == "a":
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "nav":
            self.inside = False


class Fast4IntegrationTests(SimpleTestCase):
    def test_all_four_pages_link_to_each_other_with_local_read_only_routes(self):
        routes = [
            reverse(f"editorial_{name}:index")
            for name in ("dashboard", "search", "followup", "export")
        ]
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(Navigation(response.content.decode()).links, routes)
                self.assertContains(response, 'lang="ar" dir="rtl"')
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertContains(response, "NOT_DEPLOYED")
