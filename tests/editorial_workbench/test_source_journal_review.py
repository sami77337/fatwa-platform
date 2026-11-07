"""Exercise #177's case comparison against a local, disposable saved event journal."""

import os
import secrets
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, SimpleTestCase, override_settings

from apps.fast9_case_source_join.source_history import sample_source_events, source_receipt
from apps.fast9_case_source_join.source_journal import JOURNAL_FILENAME, append_source_event

from .test_source_review import TaggedText


@override_settings(ALLOWED_HOSTS=["localhost", "external.invalid"])
class SourceJournalReviewTests(SimpleTestCase):
    case_url = "/dev/editorial-workbench/intake-7"
    samples_url = case_url + "/source-review"
    url = samples_url + "/journal"
    setting = "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR"

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.directory = Path(directory)
        self.enterContext(patch.dict(os.environ, {self.setting: directory}))

    def read(self, url=None, **extra):
        return self.client.get(url or self.url, HTTP_HOST="localhost", **extra)

    def append(self, event):
        return append_source_event(self.directory, event, synthetic_fixtures_only=True)

    @staticmethod
    def contents(response, element):
        return "".join(TaggedText(response.content.decode(), element).parts)

    def test_configured_case_and_sample_link_to_distinct_saved_view(self):
        for url in (self.case_url, self.samples_url):
            with self.subTest(url=url):
                self.assertContains(self.read(url), f'href="{self.url}"')
        self.assertNotContains(self.read("/dev/editorial-workbench/intake-1"), f'href="{self.url}"')
        with patch.dict(os.environ, {self.setting: ""}):
            self.assertNotContains(self.read(self.case_url), f'href="{self.url}"')
            response = self.read()
            self.assertContains(response, "لم يُضبط", status_code=503)
            self.assertNotIn(b"data-status=", response.content)

    def test_desk_acknowledges_only_the_displayed_version_and_updates_the_readonly_workbench(self):
        from apps.editorial_workbench import reviewer_settings as desk

        received, correction = sample_source_events("intake-7", "corrected")
        self.append(received)
        token = secrets.token_hex(32)
        self.enterContext(
            patch.dict(
                os.environ,
                {"FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256": sha256(token.encode()).hexdigest()},
            )
        )
        with self.settings(
            SETTINGS_MODULE=desk.__name__,
            ROOT_URLCONF=desk.ROOT_URLCONF,
            MIDDLEWARE=desk.MIDDLEWARE,
            ALLOWED_HOSTS=["127.0.0.1"],
        ):
            client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
            url = "/review/"
            ctx = client.get(url).context
            fields = {
                "count": ctx["current_count"],
                "source_digest": ctx["source_digest"],
                "draft_digest": ctx["draft_digest"],
                "token": token,
            }

            def post():
                return client.post(
                    url, urlencode(fields), content_type="application/x-www-form-urlencoded"
                )

            self.assertEqual(post().status_code, 403)
            fields["csrfmiddlewaretoken"] = str(ctx["csrf_token"])
            fields["token"] = "bad-token"
            self.assertEqual(post().status_code, 403)
            fields["token"] = token
            self.assertEqual(post().status_code, 303)
            self.assertContains(client.get(url), 'data-state="current"')
            self.append(correction)
            conflict = post()
            self.assertContains(conflict, 'href="#event-2"', status_code=409)
            self.assertContains(conflict, 'data-diff="edited"', status_code=409)
            self.assertContains(conflict, "<del>", status_code=409)
            self.assertContains(conflict, "<ins>", status_code=409)
        self.assertContains(self.read(), 'data-state="changed"')

    def test_empty_history_does_not_create_a_store_or_imply_the_source_is_unchanged(self):
        response = self.read()
        self.assertContains(response, "لا توجد أحداث محفوظة لهذه القضية", status_code=404)
        self.assertNotIn(b"data-status=", response.content)
        self.assertEqual(self.client.head(self.url, HTTP_HOST="localhost").status_code, 404)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_missing_case_does_not_borrow_history_from_another_case(self):
        self.append(source_receipt("intake-1"))
        response = self.read()
        self.assertContains(response, "لا توجد أحداث محفوظة لهذه القضية", status_code=404)
        self.assertNotIn(b"data-status=", response.content)

    def test_new_reads_follow_only_saved_events_and_preserve_text_after_restoration_and_deletion(
        self,
    ):
        received, corrected, restored = sample_source_events("intake-7", "restored")
        deleted = replace(
            restored,
            kind="deleted",
            event_id="after-restore",
            prior_event_id=restored.event_id,
            body_utf8=None,
        )
        original = received.body_utf8.decode()
        for index, (event, status) in enumerate(
            (
                (received, "SOURCE_TEXT_UNCHANGED"),
                (corrected, "SOURCE_TEXT_CHANGED_REVIEW_NEEDED"),
                (restored, "SOURCE_TEXT_CHANGED_REVIEW_NEEDED"),
                (deleted, "SOURCE_DELETED_REVIEW_NEEDED"),
            ),
            1,
        ):
            with self.subTest(index=index):
                self.append(event)
                before = (self.directory / JOURNAL_FILENAME).read_bytes()
                names = sorted(p.name for p in self.directory.iterdir())
                response = self.read()
                self.assertContains(response, f'data-status="{status}"')
                self.assertContains(response, "data-kind=", count=index)
                self.assertNotContains(response, 'id="source-review-samples"')
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(self.contents(response, "source-journal-tip"), event.event_id)
                self.assertEqual(self.contents(response, "source-review-original"), original)
                latest = self.contents(response, "source-review-latest")
                if event.body_utf8 is None:
                    self.assertIn("حذف", latest)
                else:
                    self.assertEqual(latest, event.body_utf8.decode())
                if index > 1:
                    self.assertIn(
                        corrected.body_utf8.decode(),
                        self.contents(response, "source-review-timeline"),
                    )
                head = self.client.head(self.url, HTTP_HOST="localhost")
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b"")
                self.assertEqual(before, (self.directory / JOURNAL_FILENAME).read_bytes())
                self.assertEqual(names, sorted(p.name for p in self.directory.iterdir()))

    def test_corruption_is_an_error_with_no_local_details_or_sample_fallback(self):
        db = self.directory / JOURNAL_FILENAME
        db.write_bytes(b"synthetic-private-error-marker")
        response = self.read()
        self.assertContains(response, "تعذّرت قراءة سجل المصدر أو التحقق", status_code=503)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(str(self.directory).encode(), response.content)
        self.assertNotIn(b"synthetic-private-error-marker", response.content)
        self.assertNotIn(b"data-status=", response.content)
        self.assertEqual(db.read_bytes(), b"synthetic-private-error-marker")

    def test_guards_reject_overrides_writes_remote_peers_and_production_before_storage_read(self):
        target = "apps.editorial_workbench.source_review.read_case_review"
        with patch(target, side_effect=AssertionError("must not read storage")):
            for q in ("sample=received", "path=/tmp/stash", "case_key=intake-1", "revision=1"):
                self.assertEqual(self.read(self.url + "?" + q).status_code, 400)
            self.assertEqual(self.client.post(self.url, HTTP_HOST="localhost").status_code, 405)
            self.assertEqual(self.read(REMOTE_ADDR="192.0.2.10").status_code, 404)
            self.assertEqual(
                self.client.get(self.url, HTTP_HOST="external.invalid").status_code, 404
            )
            with self.settings(FATWA_PRODUCTION=True):
                self.assertEqual(self.read().status_code, 404)
            with patch.dict(os.environ, {self.setting: "relative-dir"}):
                self.assertEqual(self.read().status_code, 503)
