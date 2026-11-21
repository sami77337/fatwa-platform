"""Actual campaign dispatcher, signed composer, browser auth and final rendering."""

import json
from hashlib import sha256
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from tests.casework.test_http import hidden, post

from . import editor
from .models import CitationSet
from .test_support import FEATURES, CitationFixture


@override_settings(**FEATURES)
class CitationHTTPTests(CitationFixture, TransactionTestCase):
    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        login = client.get("/casework/staff/login/")
        name = {"editor": "editor", "other": "reviewer", "publisher": "publisher"}[subject]
        self.assertEqual(
            post(
                client,
                "/casework/staff/login/",
                {"credential": f"synthetic-{name}-credential-32-characters"},
                login,
            ).status_code,
            303,
        )
        return client, client.get("/casework/staff/")

    def action(self, client, page, action="precise_compose", **values):
        payload = {
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            "case_ref": self.receipt["public_ref"],
            "action": action,
            **values,
        }
        return client.post(
            "/casework/staff/", urlencode(payload), content_type="application/x-www-form-urlencoded"
        )

    def add(self, client, page):
        found = self.action(
            client,
            page,
            state=hidden(page, "state"),
            text=self.answer_text,
            phrase="عبارة محددة",
            command="find",
        )
        self.assertEqual(found.status_code, 200, found.content)
        added = self.action(
            client,
            found,
            state=hidden(found, "state"),
            text=self.answer_text,
            phrase="عبارة محددة",
            occurrence=str(self.answer_text.rindex("عبارة محددة")),
            command="add",
            selection="LIBRARY:" + self.material["version_id"],
            mode="TEXT",
            start="0",
            end="12",
        )
        self.assertEqual(added.status_code, 200, added.content)
        return added

    def test_native_find_add_save_independent_review_print_export_and_revocation(self):
        client, home = self.login()
        page = self.action(client, home, "precise_open")
        self.assertEqual(page.status_code, 200, page.content)
        added = self.add(client, page)
        self.assertContains(added, self.answer_text)
        saved = self.action(
            client,
            added,
            state=hidden(added, "state"),
            text=self.answer_text,
            command="save",
            confirmed="yes",
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        row = CitationSet.objects.get()
        reviewer, home = self.login("other")
        opened = self.action(reviewer, home, "precise_open")
        reviewed = self.action(
            reviewer,
            opened,
            "precise_review",
            state=hidden(opened, "state"),
            set_id=str(row.pk),
            decision="APPROVE",
            note="فحص الموضع بالواجهة",
            confirmed="yes",
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.content)
        anchor = row.anchors.get()
        source = client.get(f"/casework/precise-citations/sources/{anchor.pk}/")
        self.assertContains(source, '<mark id="cited-position">مصدر اصطناعي')
        original = client.get(f"/casework/precise-citations/sources/{anchor.pk}/file/")
        expected_bytes = "مصدر اصطناعي دقيق محفوظ للإحالة".encode("utf-8")
        self.assertEqual(original.content, expected_bytes)
        self.assertEqual(original["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(original["X-Content-SHA256"], sha256(expected_bytes).hexdigest())
        printed = client.get(f"/casework/precise-citations/print/{row.pk}/")
        self.assertContains(printed, "محارف المصدر 1–12")
        exported = client.get(f"/casework/precise-citations/export/{row.pk}/")
        data = json.loads(exported.content)
        self.assertEqual(data["citations"][0]["phrase"], "عبارة محددة")
        self.assertNotIn("case_id", exported.content.decode())
        self.assertNotIn("source.txt", exported.content.decode())
        self.assertIn("no-store", printed["Cache-Control"])
        self.authority.denied.add("CITE")
        self.assertEqual(
            client.get(f"/casework/precise-citations/print/{row.pk}/").status_code, 404
        )
        self.assertEqual(
            client.get(f"/casework/precise-citations/sources/{anchor.pk}/file/").status_code, 404
        )

    def test_signed_draft_cross_actor_and_csrf_replay_denied(self):
        client, home = self.login()
        opened = self.action(client, home, "precise_open")
        other, home2 = self.login("other")
        replay = self.action(
            other,
            home2,
            state=hidden(opened, "state"),
            text=self.answer_text,
            command="find",
            phrase="عبارة",
        )
        self.assertEqual(replay.status_code, 409)
        denied = client.post(
            "/casework/staff/", {"action": "precise_open", "case_ref": self.receipt["public_ref"]}
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(CitationSet.objects.count(), 0)

    def test_late_render_revocation_rolls_back_new_answer_and_citation(self):
        client, home = self.login()
        opened = self.action(client, home, "precise_open")
        added = self.add(client, opened)
        real = editor.render

        def revoke(*args, **kwargs):
            value = real(*args, **kwargs)
            self.citation_authority.denied.add("EDIT")
            return value

        with patch.object(editor, "render", side_effect=revoke):
            failed = self.action(
                client,
                added,
                state=hidden(added, "state"),
                text=self.answer_text,
                command="save",
                confirmed="yes",
            )
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(CitationSet.objects.count(), 0)
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_late_source_render_cannot_return_stale_private_text(self):
        row = self.save_citations()
        client, _ = self.login()
        real = editor.render

        def revoke(*args, **kwargs):
            value = real(*args, **kwargs)
            self.authority.denied.add("READ")
            return value

        with patch.object(editor, "render", side_effect=revoke):
            response = client.get(f"/casework/precise-citations/sources/{row['entries'][0]['id']}/")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "مصدر اصطناعي", status_code=404)

    def test_canonical_approval_rejects_unreviewed_then_accepts_exact_review(self):
        row = self.save_citations()
        args = dict(
            self.common,
            answer_id=row["answer_id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        with self.assertRaisesRegex(cases.CaseConflict, "human_review"):
            cases.record_decision(**args)
        self.review_citations(row)
        approved = cases.record_decision(**args)
        self.assertEqual(approved["approved_answer_id"], row["answer_id"])
        self.authority.denied.add("CITE")
        from apps.casework import delivery

        with self.assertRaises(cases.CaseConflict):
            delivery.prepare_case_delivery(**self.common)

    def test_exact_pdf_page_opens_original_and_marks_paragraph_precision_limit(self):
        from apps.pdf_citations.tests import pdf_fixture

        from . import sources
        from .boundary import scope

        raw = pdf_fixture(3)["raw"]
        material = self.approve(
            self.write(file_bytes=raw, filename="exact.pdf", media_type="application/pdf")
        )
        with scope(**self.common) as guard:
            pin, _ = sources.select(
                guard,
                "LIBRARY:" + material["version_id"],
                owner_case_id=self.common["case_id"],
                location=sources.locator(
                    "PAGE", 2, 2, limitation="الصفحة الفعلية موثقة؛ لا يتوفر رابط فقرة داخلها"
                ),
            )
        entry = self.selection()
        entry["source"] = pin
        row = self.save_citations(selections=[entry])
        client, _ = self.login()
        url = f"/casework/precise-citations/sources/{row['entries'][0]['id']}/"
        response = client.get(url)
        self.assertContains(response, 'href="file/#page=2"')
        self.assertContains(response, "لا يتوفر رابط فقرة داخلها")
        document = client.get(url + "file/")
        self.assertEqual(document["Content-Type"], "application/pdf")
        self.assertEqual(document.content, raw)
