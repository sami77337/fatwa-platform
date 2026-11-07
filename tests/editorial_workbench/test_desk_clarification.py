"""Exercise the local question, clarification and reading forms on one synthetic case."""

import os
import secrets
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, SimpleTestCase, override_settings
from django.utils.html import escape

from apps.editorial_workbench import reviewer_settings as desk
from apps.fast9_case_source_join.source_history import source_receipt
from apps.fast9_case_source_join.source_journal import append_source_event
from config.settings import development

from .test_source_review import TaggedText


@override_settings(
    SETTINGS_MODULE=desk.__name__,
    ROOT_URLCONF=desk.ROOT_URLCONF,
    MIDDLEWARE=desk.MIDDLEWARE,
    ALLOWED_HOSTS=["127.0.0.1"],
)
class ClarificationDeskTests(SimpleTestCase):
    def test_reply_reopens_the_same_case_and_stale_form_cannot_mark_it_read(self):
        directory = self.enterContext(TemporaryDirectory())
        token = secrets.token_hex(32)
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": directory,
                    "FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256": sha256(token.encode()).hexdigest(),
                },
            )
        )
        original = source_receipt("intake-7")
        append_source_event(Path(directory), original, synthetic_fixtures_only=True)
        client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        url = "/review/"

        def submit(screen, **action):
            ctx = screen.context
            fields = {
                "csrfmiddlewaretoken": str(ctx["csrf_token"]),
                "token": token,
                "count": ctx["current_count"],
                "source_digest": ctx["source_digest"],
                "draft_digest": ctx["draft_digest"],
                "thread_digest": ctx["thread_digest"],
                "reply_digest": ctx["reply_digest"],
                **action,
            }
            return client.post(
                url, urlencode(fields), content_type="application/x-www-form-urlencoded"
            )

        def queue():
            with self.settings(
                ROOT_URLCONF=development.ROOT_URLCONF, MIDDLEWARE=development.MIDDLEWARE
            ):
                return Client(HTTP_HOST="127.0.0.1").get("/dev/editorial-workbench")

        self.assertEqual(submit(client.get(url)).status_code, 303)
        prompt = "في المثال التدريبي، هل المقصود <الموعد الأول>؟"
        self.assertEqual(
            submit(client.get(url), action="request_clarification", prompt=prompt).status_code, 303
        )
        waiting = client.get(url)
        self.assertTrue(waiting.context["waiting"])
        self.assertContains(queue(), "بانتظار ردّ على الاستيضاح")
        self.assertContains(waiting, escape(prompt))
        self.assertNotContains(waiting, prompt)
        reply_key, reply_text = next(iter(waiting.context["reply_options"].items()))
        self.assertEqual(
            submit(waiting, action="simulate_reply", reply_key=reply_key).status_code, 303
        )

        stale = submit(waiting)
        self.assertEqual(stale.status_code, 409)
        updated = client.get(url)
        self.assertFalse(updated.context["waiting"])
        self.assertTrue(updated.context["has_new_reply"])
        self.assertContains(queue(), "ردّ جديد على الاستيضاح يحتاج إلى قراءة")
        self.assertEqual(updated.context["case_key"], original.case_key)
        self.assertEqual([item["kind"] for item in updated.context["thread"]], ["request", "reply"])
        self.assertContains(updated, escape(reply_text))
        question = TaggedText(updated.content.decode(), "original-question")
        self.assertEqual("".join(question.parts), original.body_utf8.decode())
        self.assertEqual(submit(updated).status_code, 303)
        self.assertFalse(client.get(url).context["has_new_reply"])
        self.assertContains(queue(), "سُجّلت قراءة آخر ردّ على الاستيضاح")
