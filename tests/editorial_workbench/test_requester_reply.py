"""Exercise a one-request handoff between two independent training browsers."""

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


@override_settings(
    SETTINGS_MODULE=desk.__name__,
    ROOT_URLCONF=desk.ROOT_URLCONF,
    MIDDLEWARE=desk.MIDDLEWARE,
    ALLOWED_HOSTS=["127.0.0.1"],
)
class RequesterReplyTests(SimpleTestCase):
    def test_rotated_and_used_codes_cannot_add_a_second_reply(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        reviewer_token = secrets.token_hex(32)
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(directory),
                    "FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256": sha256(
                        reviewer_token.encode()
                    ).hexdigest(),
                },
            )
        )
        append_source_event(directory, source_receipt("intake-7"), synthetic_fixtures_only=True)
        reviewer = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        requester = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        desk_url, reply_url = "/review/", "/review/respond/"
        prompt = "متى وصلت العينة <التدريبية>؟"
        reply = "وصلت العينة صباحًا."

        def post(client, url, screen, **fields):
            data = {"csrfmiddlewaretoken": str(screen.context["csrf_token"]), **fields}
            return client.post(
                url, urlencode(data), content_type="application/x-www-form-urlencoded"
            )

        def staff_fields(screen):
            ctx = screen.context
            return {
                "count": ctx["current_count"],
                "source_digest": ctx["source_digest"],
                "draft_digest": ctx["draft_digest"],
                "thread_digest": ctx["thread_digest"],
                "reply_digest": ctx["reply_digest"],
            }

        def staff_action(action=None, **extra):
            screen = reviewer.get(desk_url)
            fields = staff_fields(screen)
            if action:
                fields["action"] = action
            if action == "issue_reply_code":
                fields["grant_revision"] = screen.context["grant_revision"]
            return post(reviewer, desk_url, screen, **fields, **extra)

        login_url = "/review/login/"
        login = reviewer.get(login_url)
        self.assertEqual(post(reviewer, login_url, login, token=reviewer_token).status_code, 303)
        self.assertEqual(staff_action().status_code, 303)
        self.assertEqual(staff_action("request_clarification", prompt=prompt).status_code, 303)
        first = staff_action("issue_reply_code")
        self.assertEqual(first.status_code, 200)
        old_code = first.context["issued_code"]
        second = staff_action("issue_reply_code")
        new_code = second.context["issued_code"]
        self.assertTrue(old_code and new_code)
        self.assertNotEqual(old_code, new_code)

        entry = requester.get(reply_url)
        self.assertNotContains(entry, escape(prompt))
        denied = post(requester, reply_url, entry, action="open", code=old_code)
        self.assertNotContains(denied, escape(prompt), status_code=403)
        opened = post(requester, reply_url, entry, action="open", code=new_code)
        self.assertEqual(opened.context["phase"], "compose")
        self.assertContains(opened, escape(prompt))
        self.assertNotContains(opened, second.context["draft_digest"])

        self.assertRedirects(requester.get(desk_url), login_url, fetch_redirect_response=False)
        login_attempt = post(requester, login_url, requester.get(login_url), token=new_code)
        self.assertNotContains(login_attempt, escape(prompt), status_code=403)
        staff_attempt = staff_fields(second)
        staff_attempt["token"] = new_code
        self.assertEqual(post(requester, desk_url, entry, **staff_attempt).status_code, 403)

        submission = {
            "action": "reply",
            "code": new_code,
            "form_proof": opened.context["form_proof"],
            "text": reply,
        }
        sent = post(requester, reply_url, opened, **submission)
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.context["phase"], "sent")
        self.assertEqual(post(requester, reply_url, opened, **submission).status_code, 403)
        reviewed = reviewer.get(desk_url)
        self.assertContains(reviewed, reply)
        reference = sent.context["reply_reference"]
        self.assertRegex(reference, r"^R-[0-9]{3}-[0-9A-F]{12}$")
        self.assertContains(reviewed, reference)
        self.assertEqual(
            [turn["kind"] for turn in reviewed.context["thread"]], ["request", "reply"]
        )
        self.assertTrue(reviewed.context["thread"][-1]["from_requester"])
        self.assertTrue(reviewed.context["has_new_reply"])
