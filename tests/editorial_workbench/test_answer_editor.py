"""Start an edit from a prior version without overwriting newer work or evidence."""

import os
import secrets
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, SimpleTestCase, override_settings

from apps.editorial_workbench import reviewer_settings as desk
from apps.fast9_case_source_join.answer_drafts import AUTHOR
from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.source_journal import (
    append_source_event,
    history_digest,
    read_case_review,
    save_answer_draft,
)


@override_settings(
    SETTINGS_MODULE=desk.__name__,
    ROOT_URLCONF=desk.ROOT_URLCONF,
    MIDDLEWARE=desk.MIDDLEWARE,
    ALLOWED_HOSTS=["127.0.0.1"],
)
class AnswerEditorTests(SimpleTestCase):
    def test_historical_start_is_readonly_and_stale_work_requires_a_new_explicit_save(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        token = secrets.token_hex(32)
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(directory),
                    "FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256": sha256(token.encode()).hexdigest(),
                },
            )
        )
        original, correction = sample_source_events("intake-7", "corrected")

        def append(text, base_revision, events):
            return save_answer_draft(
                directory,
                author=AUTHOR,
                title="عنوان تدريبي",
                body=text,
                base_revision=base_revision,
                count=len(events),
                source_digest=history_digest(events),
                reply_digest="",
                evidence_seen=True,
                synthetic_fixtures_only=True,
            )

        events = append_source_event(directory, original, synthetic_fixtures_only=True)
        append("النسخة الأولى", 0, events)
        append("النسخة الثانية", 1, events)
        browser = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        url = "/review/author/draft/"
        login = "/review/author/login/"

        def post(path, screen, fields):
            data = {"csrfmiddlewaretoken": str(screen.context["csrf_token"]), **fields}
            return browser.post(
                path, urlencode(data), content_type="application/x-www-form-urlencoded"
            )

        self.assertEqual(post(login, browser.get(login), {"token": token}).status_code, 303)
        start = browser.get(url, {"from": "1"})
        self.assertContains(start, "النسخة الأولى")
        self.assertContains(start, "النسخة الثانية")
        self.assertEqual(start.context["base_revision"], 2)
        self.assertEqual(start.context["restored_from"], 1)
        self.assertEqual(len(read_case_review(directory, synthetic_fixtures_only=True).drafts), 2)

        events = append_source_event(directory, correction, synthetic_fixtures_only=True)
        append("تعديل من نافذة أخرى", 2, events)
        form = {"title": "عنوان تدريبي", "body": "نصٌّ حرّرته من النسخة الأولى", "evidence_seen": "1"}
        version_fields = ("count", "base_revision", "source_digest", "reply_digest")
        conflict = post(url, start, {**{k: start.context[k] for k in version_fields}, **form})
        self.assertContains(conflict, form["body"], status_code=409)
        self.assertContains(conflict, "تعديل من نافذة أخرى", status_code=409)
        self.assertTrue(conflict.context["changed_evidence"])
        self.assertTrue(conflict.context["changed_revision"])
        self.assertEqual(
            post(
                url, conflict, {**{k: conflict.context[k] for k in version_fields}, **form}
            ).status_code,
            303,
        )
        versions = read_case_review(directory, synthetic_fixtures_only=True).drafts
        self.assertEqual(
            [v.body for v in versions],
            ["النسخة الأولى", "النسخة الثانية", "تعديل من نافذة أخرى", form["body"]],
        )
        self.assertEqual(versions[-1].source_count, 2)

    def test_expired_author_reauthenticates_without_disclosing_case_or_saving_on_resume(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        token = secrets.token_hex(32)
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(directory),
                    "FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256": sha256(token.encode()).hexdigest(),
                },
            )
        )
        original, correction = sample_source_events("intake-7", "corrected")
        append_source_event(directory, original, synthetic_fixtures_only=True)
        client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        url, login = "/review/author/draft/", "/review/author/login/"

        def post(path, screen, fields):
            data = {"csrfmiddlewaretoken": str(screen.context["csrf_token"]), **fields}
            return client.post(
                path, urlencode(data), content_type="application/x-www-form-urlencoded"
            )

        self.assertEqual(post(login, client.get(login), {"token": token}).status_code, 303)
        opened = client.get(url)
        pins = ("base_revision", "count", "source_digest", "reply_digest")
        words = {"title": "تجربة", "body": "جوابي <الدقيق> قبل انتهاء الجلسة"}
        typed = {**{k: opened.context[k] for k in pins}, **words}
        client.cookies.pop("fatwa_training_author")
        with (
            patch(
                "apps.editorial_workbench.answer_editor.read_case_review",
                side_effect=AssertionError,
            ),
            patch(
                "apps.editorial_workbench.answer_editor.save_answer_draft",
                side_effect=AssertionError,
            ),
        ):
            locked = post(url, opened, {**typed, "evidence_seen": "1"})
            self.assertContains(locked, "جوابي &lt;الدقيق&gt;", status_code=403)
            self.assertNotContains(locked, 'id="case-evidence"', status_code=403)
            denied = post(url, locked, {**typed, "action": "resume", "token": "wrong"})
            self.assertContains(denied, 'id="recover-draft-form"', status_code=403)

        append_source_event(directory, correction, synthetic_fixtures_only=True)
        resumed = post(url, denied, {**typed, "action": "resume", "token": token})
        self.assertContains(resumed, "جوابي &lt;الدقيق&gt;")
        self.assertTrue(resumed.context["changed_evidence"])
        self.assertEqual(read_case_review(directory, synthetic_fixtures_only=True).drafts, ())
        final = {**{k: resumed.context[k] for k in pins}, **words, "evidence_seen": "1"}
        self.assertEqual(post(url, resumed, final).status_code, 303)
        (saved,) = read_case_review(directory, synthetic_fixtures_only=True).drafts
        self.assertEqual((saved.body, saved.source_count), (words["body"], 2))
