"""Rendered warnings on fixed, read-only examples. No database or provider usage."""

from html.parser import HTMLParser
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.fast9_case_source_join.source_history import CORRECTION_BODIES, source_receipt


class TaggedText(HTMLParser):
    """Collect the visible text inside the element with the given ID."""

    def __init__(self, html, target):
        super().__init__()
        self.target = target
        self.depth = 0
        self.parts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if self.depth or dict(attrs).get("id") == self.target:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, value):
        if self.depth:
            self.parts.append(value)


@override_settings(ALLOWED_HOSTS=["localhost", "external.invalid"])
class SourceReviewScreenTests(SimpleTestCase):
    desk = "/dev/editorial-workbench"
    url = desk + "/intake-7/source-review"

    def read(self, path=None, **opts):
        return self.client.get(path or self.url, HTTP_HOST="localhost", **opts)

    def test_only_bound_draft_has_entry_link(self):
        detail = self.read(self.desk + "/intake-7")
        self.assertContains(detail, f'href="{self.url}"')
        for key in ("intake-1", "batch-synthetic-jsonl-2", "history"):
            with self.subTest(key=key):
                self.assertNotContains(self.read(self.desk + "/" + key), 'id="source-review-link"')
                self.assertEqual(self.read(f"{self.desk}/{key}/source-review").status_code, 404)

    def test_fixed_scenarios_preserve_text_and_do_not_infer_clearance(self):
        original = source_receipt("intake-7").body_utf8.decode()
        changed = CORRECTION_BODIES[0].decode()
        for sample, status, latest, count in (
            ("received", "SOURCE_TEXT_UNCHANGED", original, 1),
            ("corrected", "SOURCE_TEXT_CHANGED_REVIEW_NEEDED", changed, 2),
            ("deleted", "SOURCE_DELETED_REVIEW_NEEDED", None, 3),
            ("restored", "SOURCE_TEXT_CHANGED_REVIEW_NEEDED", original, 3),
        ):
            with self.subTest(sample=sample):
                response = self.read(self.url + "?sample=" + sample)
                self.assertContains(response, f'data-status="{status}"')
                self.assertContains(response, "data-kind=", count=count)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                html = response.content.decode()
                self.assertEqual(
                    "".join(TaggedText(html, "source-review-original").parts), original
                )
                last = "".join(TaggedText(html, "source-review-latest").parts)
                if latest is None:
                    self.assertIn("حذف", last)
                else:
                    self.assertEqual(last, latest)
                if sample == "restored":
                    self.assertIn(
                        changed, "".join(TaggedText(html, "source-review-timeline").parts)
                    )

    def test_arbitrary_history_and_revision_overrides_are_rejected(self):
        for query in (
            "sample=unknown",
            "sample=",
            "sample=received&sample=deleted",
            "body=secret",
            "revision=2",
            "event=deleted",
        ):
            with self.subTest(query=query):
                self.assertEqual(self.read(self.url + "?" + query).status_code, 400)

    def test_write_and_remote_requests_are_denied(self):
        self.assertEqual(self.client.head(self.url, HTTP_HOST="localhost").status_code, 200)
        self.assertEqual(self.client.post(self.url, HTTP_HOST="localhost").status_code, 405)
        self.assertEqual(self.read(REMOTE_ADDR="192.0.2.10").status_code, 404)
        self.assertEqual(self.client.get(self.url, HTTP_HOST="external.invalid").status_code, 404)
        with self.settings(FATWA_PRODUCTION=True):
            self.assertEqual(self.read().status_code, 404)

    def test_inconsistent_source_hides_report_and_error_details(self):
        with patch(
            "apps.fast9_case_source_join.draft_source_review.inspect_draft_source",
            side_effect=ValueError("private failure details"),
        ):
            response = self.read()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"data-status=", response.content)
        self.assertNotIn(b"private failure details", response.content)
