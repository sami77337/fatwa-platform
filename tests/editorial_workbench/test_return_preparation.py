"""A private preparation preview joins the real local human review journey."""

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

URL = "/review/author/return-preparation/"


@override_settings(
    SETTINGS_MODULE=desk.__name__,
    ROOT_URLCONF=desk.ROOT_URLCONF,
    MIDDLEWARE=desk.MIDDLEWARE,
    ALLOWED_HOSTS=["127.0.0.1"],
)
class ReturnPreparationTests(SimpleTestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.tokens = {role: secrets.token_hex(32) for role in ("author", "reviewer", "operator")}
        values = {
            f"FATWA_SYNTHETIC_{role.upper()}_TOKEN_SHA256": sha256(token.encode()).hexdigest()
            for role, token in self.tokens.items()
        }
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    **values,
                    "FATWA_PRODUCTION": "0",
                    "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(self.directory),
                },
            )
        )

    def browser(self, role=None):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1")
        if role:
            login = {
                "author": "/review/author/login/",
                "reviewer": "/review/login/",
                "operator": "/review/operations/login/",
            }[role]
            result = self.post(client, login, client.get(login), token=self.tokens[role])
            self.assertEqual(result.status_code, 303)
        return client

    def post(self, client, url, screen, **fields):
        return client.post(
            url,
            urlencode({"csrfmiddlewaretoken": str(screen.context["csrf_token"]), **fields}),
            content_type="application/x-www-form-urlencoded",
        )

    def seed_draft(self, body="نصٌّ تدريبي <دقيق>\r\nمع تشكيلٍ ومسافات.  ", title="عنوان التدريب"):
        state = read_case_review(self.directory, synthetic_fixtures_only=True)
        if not state.events:
            (first,) = sample_source_events("intake-7", "received")
            append_source_event(self.directory, first, synthetic_fixtures_only=True)
            state = read_case_review(self.directory, synthetic_fixtures_only=True)
        return save_answer_draft(
            self.directory,
            author=AUTHOR,
            base_revision=state.drafts[-1].revision if state.drafts else 0,
            count=len(state.events),
            source_digest=history_digest(state.events),
            reply_digest=state.reply_digest,
            title=title,
            body=body,
            evidence_seen=True,
            synthetic_fixtures_only=True,
        )

    def files(self):
        return {path.name: path.read_bytes() for path in self.directory.iterdir() if path.is_file()}

    def test_only_author_and_reviewer_can_read_exact_latest_draft(self):
        draft = self.seed_draft()
        for role in (None, "operator"):
            with self.subTest(role=role):
                response = self.browser(role).get(URL)
                self.assertRedirects(
                    response, "/review/author/login/", fetch_redirect_response=False
                )
                self.assertNotIn(draft.body.encode(), response.content)
        for role in ("author", "reviewer"):
            with self.subTest(role=role):
                response = self.browser(role).get(URL)
                self.assertContains(response, "تحضير إرجاع الجواب")
                self.assertContains(response, "نصٌّ تدريبي &lt;دقيق&gt;&#13;\n")
                self.assertContains(response, "بانتظار اعتماد المفتي عبر جهة تحقق موثوقة")
                self.assertEqual(response.context["candidate"].draft, draft)
                self.assertEqual(response["Cache-Control"], "no-store")
                self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])

    def test_explicit_split_preview_is_lossless_and_never_writes(self):
        body = "  كلمةٌ أولى\r\nكلمة ثانية\t ونهاية.  "
        self.seed_draft(body=body)
        client = self.browser("author")
        before = self.files()
        undecided = client.get(URL, {"max_chars": "14"})
        self.assertContains(undecided, "يتطلب تقسيم النص اختيارًا صريحًا")
        self.assertEqual(undecided.context["segments"], ())
        preview = client.get(URL, {"max_chars": "14", "split": "1"})
        parts = preview.context["segments"]
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(part.exact_text for part in parts), body)
        self.assertTrue(all(part.length <= 14 for part in parts))
        self.assertContains(preview, "حدّ تدريبي")
        self.assertEqual(client.head(URL, {"max_chars": "14", "split": "1"}).status_code, 200)
        self.assertEqual(self.files(), before)

    def test_query_cannot_supply_authority_content_or_ambiguous_options(self):
        self.seed_draft()
        client = self.browser("reviewer")
        before = self.files()
        for query in (
            "max_chars=0",
            "max_chars=6001",
            "max_chars=-1",
            "max_chars=01",
            "max_chars=",
            "max_chars=4&max_chars=5",
            "split=0",
            "split=1&split=1",
            "verified=1",
            "revision=1",
            "approval=yes",
            "text=injected",
            "recipient=elsewhere",
        ):
            with self.subTest(query=query):
                response = client.get(URL + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, "<دقيق>", status_code=400)
        self.assertEqual(self.files(), before)

    def test_unsplittable_text_is_reported_without_truncation_or_500(self):
        self.seed_draft(body="كلمةطويلةبلامسافات")
        client = self.browser("author")
        response = client.get(URL, {"max_chars": "3", "split": "1"})
        self.assertContains(response, "تجاوزت كلمة واحدة الحدّ")
        self.assertContains(response, "كلمةطويلةبلامسافات")
        self.assertEqual(response.context["segments"], ())
        self.seed_draft(body="أ " * 40)
        overflow = client.get(URL, {"max_chars": "2", "split": "1"})
        self.assertContains(overflow, "أكثر من 16 جزءًا")
        self.assertEqual(overflow.context["segments"], ())

    def test_empty_read_and_bad_storage_do_not_create_an_outbox(self):
        client = self.browser("author")
        empty = client.get(URL)
        self.assertContains(empty, "لم يُحفظ سؤال لهذه القضية")
        self.assertEqual(list(self.directory.iterdir()), [])
        with patch.dict(os.environ, {"FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": "relative-path"}):
            response = client.get(URL)
        self.assertContains(response, "تعذّر فتح سجل القضية", status_code=503)
        self.assertNotContains(response, "relative-path", status_code=503)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_mutating_methods_and_foreign_host_are_rejected(self):
        self.seed_draft()
        client = self.browser("author")
        before = self.files()
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(client, method)(URL).status_code, 405)
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            self.assertEqual(client.get(URL, HTTP_HOST="testserver").status_code, 404)
        self.assertEqual(self.files(), before)

    def test_new_source_and_draft_are_refreshed_instead_of_reusing_preview(self):
        first = self.seed_draft()
        client = self.browser("author")
        opened = client.get(URL)
        self.assertNotIn("answer_evidence_stale", opened.context["candidate"].blockers)
        _, correction = sample_source_events("intake-7", "corrected")
        append_source_event(self.directory, correction, synthetic_fixtures_only=True)
        stale = client.get(URL)
        self.assertIn("answer_evidence_stale", stale.context["candidate"].blockers)
        second = self.seed_draft(body="مسودة أحدث بعد مراجعة السؤال.")
        fresh = client.get(URL)
        self.assertEqual(fresh.context["candidate"].draft.revision, first.revision + 1)
        self.assertEqual(fresh.context["candidate"].draft, second)
        self.assertNotIn("answer_evidence_stale", fresh.context["candidate"].blockers)
        self.assertIn("technical_review_required", fresh.context["candidate"].blockers)

    def test_connected_requester_author_and_reviewer_journey_stops_at_trusted_approval(self):
        (first,) = sample_source_events("intake-7", "received")
        append_source_event(self.directory, first, synthetic_fixtures_only=True)
        reviewer, author, requester = (
            self.browser("reviewer"),
            self.browser("author"),
            self.browser(),
        )

        def staff_action(action, **extra):
            page = reviewer.get("/review/")
            ctx = page.context
            fields = {
                key: ctx[key]
                for key in (
                    "source_digest",
                    "draft_digest",
                    "thread_digest",
                    "reply_digest",
                )
            }
            fields["count"] = ctx["current_count"]
            if action == "issue_reply_code":
                fields["grant_revision"] = ctx["grant_revision"]
            return self.post(reviewer, "/review/", page, action=action, **fields, **extra)

        self.assertEqual(staff_action("read").status_code, 303)
        self.assertEqual(
            staff_action("request_clarification", prompt="اذكر وصف العينة التدريبية.").status_code,
            303,
        )
        grant = staff_action("issue_reply_code")
        code = grant.context["issued_code"]
        portal = "/review/respond/"
        opened = self.post(requester, portal, requester.get(portal), action="open", code=code)
        reply = self.post(
            requester,
            portal,
            opened,
            action="reply",
            code=code,
            form_proof=opened.context["form_proof"],
            text="هذه عينة اصطناعية فقط.",
        )
        self.assertEqual(reply.context["phase"], "sent")
        self.assertRedirects(
            requester.get(URL), "/review/author/login/", fetch_redirect_response=False
        )
        self.assertEqual(staff_action("read").status_code, 303)

        editor = author.get("/review/author/draft/")
        fields = {
            key: editor.context[key]
            for key in (
                "base_revision",
                "count",
                "source_digest",
                "reply_digest",
            )
        }
        saved = self.post(
            author,
            "/review/author/draft/",
            editor,
            **fields,
            title="تجربة وصل المكاتب",
            body="نص كتبه الإنسان للعينة التدريبية فقط.",
            evidence_seen="1",
        )
        self.assertEqual(saved.status_code, 303)

        def handoff(client, action):
            page = client.get("/review/author/notes/")
            pins = {key: page.context[key] for key in ("revision", "draft_digest", "note_count")}
            return self.post(client, "/review/author/notes/", page, **pins, action=action, text="")

        self.assertEqual(handoff(reviewer, "submit").status_code, 403)
        self.assertEqual(handoff(author, "submit").status_code, 303)
        self.assertEqual(handoff(author, "confirm").status_code, 403)
        self.assertEqual(handoff(reviewer, "confirm").status_code, 303)
        ready = reviewer.get(URL)
        self.assertEqual(ready.context["candidate"].blockers, ())
        self.assertTrue(ready.context["candidate"].technical_review_current)
        self.assertContains(ready, "اكتملت متطلبات التحضير لهذه النسخة")
        self.assertContains(ready, "بانتظار اعتماد المفتي عبر جهة تحقق موثوقة")
        for path in ("/review/author/history/", "/review/author/notes/"):
            self.assertContains(author.get(path), URL)
        self.assertEqual(len(list(self.directory.iterdir())), 1)
        self.assertEqual(
            [
                n.action
                for n in read_case_review(
                    self.directory,
                    synthetic_fixtures_only=True,
                ).draft_notes
            ],
            ["submit", "confirm"],
        )
