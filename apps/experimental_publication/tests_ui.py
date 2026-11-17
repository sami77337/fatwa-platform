"""Focused V11 HTTP continuity on the existing publication authority and records."""

from dataclasses import replace
from html.parser import HTMLParser
from unittest.mock import patch
from uuid import uuid4

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from tests.casework.test_http import WEB_SETTINGS, post

from . import services
from . import tests as fixtures
from .models import PublicationAction, PublicationEdition


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms, self.current, self.textarea = [], None, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {}
        elif self.current is not None and tag == "input" and "name" in attrs:
            if attrs.get("type") != "checkbox":
                self.current[attrs["name"]] = attrs.get("value", "")
        elif self.current is not None and tag == "textarea" and "name" in attrs:
            self.textarea = attrs["name"]
            self.current[self.textarea] = ""

    def handle_data(self, data):
        if self.textarea:
            self.current[self.textarea] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.textarea = None
        if tag == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


def fields(page, action, edition_id=None):
    return next(
        form
        for form in Forms(page.content.decode()).forms
        if form.get("action") == action
        and (edition_id is None or form.get("edition_id") == edition_id)
    )


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "apps.experimental_publication.urls",
        "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
    }
)
class PublicationContinuityTests(TransactionTestCase):
    setUp = fixtures.PublicationTests.setUp
    edition = fixtures.PublicationTests.edition
    act = fixtures.PublicationTests.act
    publish = fixtures.PublicationTests.publish

    def login(self, subject="editor"):
        setting = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        setting.enable()
        self.addCleanup(setting.disable)
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        with patch.object(
            self.directory, "authenticate", return_value=self.directory.resolve(subject)
        ):
            result = post(client, "/casework/staff/login/", {"credential": "S" * 64}, page)
        self.assertEqual(result.status_code, 303, result.content)
        return client, client.get("/casework/staff/")

    def open(self, client, page, **extra):
        return post(
            client,
            "/casework/staff/",
            {
                "action": "pub_open",
                "case_ref": self.receipt["public_ref"],
                **extra,
            },
            page,
        )

    def test_historical_and_current_states_offer_only_applicable_actions(self):
        first = self.edition()
        self.act(first, "REVIEW", reviewed=True)
        second = self.edition(body="new current candidate")
        client, page = self.login("publisher")
        page = self.open(client, page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "مرشح سابق متوقف")
        forms = Forms(page.content.decode()).forms
        self.assertEqual(
            [f["edition_id"] for f in forms if f.get("action") == "pub_review"], [second["id"]]
        )
        self.assertFalse(any(f.get("action") == "pub_approve" for f in forms))
        self.publish(second)
        page = self.open(client, page)
        self.assertContains(page, "متاحة حاليًا في المكتبة المغلقة")
        self.assertContains(page, "تاريخ هذه النسخة")
        self.assertEqual(page.context["selected"]["visible_edition"]["id"], second["id"])
        third = self.edition(body="corrected new edition")
        self.publish(third)
        page = self.open(client, page)
        self.assertContains(page, "استُبدلت بنسخة نشر أحدث")
        cases.add_followup(
            token=self.receipt["token"],
            text="new material fact",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        page = self.open(client, page)
        self.assertContains(page, "متوقفة لتغيّر الجواب أو الوقائع أو المصدر")
        self.assertIsNone(page.context["selected"]["visible_edition"])
        forms = Forms(page.content.decode()).forms
        self.assertFalse(
            any(f.get("action") in {"pub_review", "pub_approve", "pub_correct"} for f in forms)
        )
        self.assertTrue(any(f.get("action") == "pub_withdraw" for f in forms))

    def test_library_detail_correction_approval_withdrawal_preserves_search_context(self):
        original = self.edition()
        self.publish(original)
        editor, page = self.login()
        page = post(
            editor,
            "/casework/staff/",
            {
                "action": "pub_library",
                "query": "نص",
                "category": "تصنيف تجريبي",
            },
            page,
        )
        page = post(editor, "/casework/staff/", fields(page, "pub_read"), page)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertNotContains(page, self.receipt["public_ref"])
        page = post(editor, "/casework/staff/", fields(page, "pub_open"), page)
        self.assertEqual(
            page.wsgi_request.publication_authorized_case_ref, self.receipt["public_ref"]
        )
        self.assertEqual(page.context["library_query"], "نص")
        self.assertEqual(page.context["library_category"], "تصنيف تجريبي")
        page = post(editor, "/casework/staff/", fields(page, "pub_correct", original["id"]), page)
        create = fields(page, "pub_create")
        self.assertEqual(create["body"], "نص محرر بلا بيانات شخصية")
        self.assertEqual(create["source_edition_id"], original["id"])
        self.assertEqual(create["library_query"], "نص")
        page = post(editor, "/casework/staff/", {**create, "body": "نص تصحيح محرر"}, page)
        self.assertEqual(page.status_code, 200, page.content)
        new = str(PublicationEdition.objects.order_by("-number").first().pk)
        self.assertEqual(page.context["selected"]["visible_edition"]["id"], original["id"])
        page = post(
            editor, "/casework/staff/", {**fields(page, "pub_review", new), "confirm": "yes"}, page
        )
        self.assertContains(page, "تنتظر النسخة موافقة مخوّل نشر مستقل")
        self.assertFalse(
            any(f.get("action") == "pub_approve" for f in Forms(page.content.decode()).forms)
        )
        self.assertFalse(
            any(f.get("action") == "pub_withdraw" for f in Forms(page.content.decode()).forms)
        )
        publisher, publisher_page = self.login("publisher")
        publisher_page = self.open(
            publisher, publisher_page, library_query="نص", library_category="تصنيف تجريبي"
        )
        publisher_page = post(
            publisher,
            "/casework/staff/",
            {
                **fields(publisher_page, "pub_approve", new),
                "confirm": "yes",
            },
            publisher_page,
        )
        self.assertEqual(publisher_page.status_code, 200, publisher_page.content)
        self.assertEqual(publisher_page.context["selected"]["visible_edition"]["id"], new)
        publisher_page = post(
            publisher,
            "/casework/staff/",
            {
                **fields(publisher_page, "pub_withdraw", new),
                "confirm": "yes",
            },
            publisher_page,
        )
        self.assertContains(publisher_page, "سُحبت النسخة من العرض والبحث")
        self.assertIsNone(publisher_page.context["selected"]["visible_edition"])
        back = fields(publisher_page, "pub_library")
        self.assertEqual((back["query"], back["category"]), ("نص", "تصنيف تجريبي"))
        library = post(publisher, "/casework/staff/", back, publisher_page)
        self.assertEqual(library.context["publications"], [])
        self.assertContains(library, 'value="تصنيف تجريبي" selected')
        self.assertEqual(PublicationEdition.objects.count(), 2)
        self.assertEqual(PublicationAction.objects.filter(action="APPROVE").count(), 2)

    def test_stale_save_preserves_copy_only_text_without_rebinding_or_permission_leak(self):
        client, page = self.login()
        page = self.open(client, page)
        stale = fields(page, "pub_create")
        attempted = "<script>synthetic escaped text</script>"
        cases.add_followup(
            token=self.receipt["token"],
            text="new material fact",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        submitted = {**stale, "title": "عنوان لم يحفظ", "category": "خاص", "body": attempted}
        page = post(client, "/casework/staff/", submitted, page)
        self.assertEqual(page.status_code, 409, page.content)
        self.assertContains(page, 'id="publication-unsaved-body" readonly', status_code=409)
        self.assertNotContains(page, "<script>", status_code=409)
        self.assertNotContains(page, 'id="publication-body"', status_code=409)
        self.assertEqual(page.context["attempted"]["body"], attempted)
        self.assertEqual(PublicationEdition.objects.count(), 0)
        saved_identity = self.directory.identities["editor"]

        def revoke(**kwargs):
            self.directory.identities["editor"] = replace(saved_identity, auth_epoch="revoked")
            raise cases.CaseConflict("case_revision_changed")

        with patch.object(services, "create_edition", side_effect=revoke):
            denied = post(client, "/casework/staff/", submitted, page)
        self.assertIn(denied.status_code, (403, 409))
        self.assertNotIn("synthetic escaped text", denied.content.decode())
        self.assertNotIn(self.receipt["public_ref"], denied.content.decode())

    def test_edition_navigation_rechecks_scope_and_form_context_is_not_authority(self):
        edition = self.edition()
        client, page = self.login()
        unknown = post(
            client, "/casework/staff/", {"action": "pub_open", "edition_id": str(uuid4())}, page
        )
        self.assertEqual(unknown.status_code, 404)
        actor = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(actor, case_keys=frozenset(["other-case"]))
        foreign = post(
            client,
            "/casework/staff/",
            {
                "action": "pub_open",
                "edition_id": edition["id"],
                "library_query": "نص",
                "library_category": "تصنيف تجريبي",
            },
            page,
        )
        self.assertEqual(
            (foreign.status_code, foreign.content), (unknown.status_code, unknown.content)
        )
        self.directory.identities["editor"] = actor
        malformed = post(
            client,
            "/casework/staff/",
            {
                "action": "pub_open",
                "edition_id": edition["id"],
                "case_ref": self.receipt["public_ref"],
            },
            page,
        )
        self.assertEqual(malformed.status_code, 400)
        too_long = post(
            client,
            "/casework/staff/",
            {
                "action": "pub_open",
                "edition_id": edition["id"],
                "library_query": "a" * 81,
                "library_category": "",
            },
            page,
        )
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(Case.objects.get(pk=self.receipt["case_id"]).revision, 3)

    def test_reading_desk_never_grants_publication_or_preview(self):
        edition = self.edition()
        self.act(edition, "REVIEW", reviewed=True)
        client, page = self.login()
        before = PublicationAction.objects.count()
        page = self.open(client, page)
        self.assertFalse(page.context["selected"]["editions"][0]["can_approve"])
        self.assertEqual(PublicationAction.objects.count(), before)
        self.assertNotContains(page, "preview_grant")
        forbidden = post(
            client,
            "/casework/staff/",
            {
                "action": "pub_approve",
                "case_ref": self.receipt["public_ref"],
                "edition_id": edition["id"],
                "confirm": "yes",
            },
            page,
        )
        self.assertEqual(forbidden.status_code, 409)
        self.assertContains(forbidden, "لا تحمل تفويض", status_code=409)
        self.assertEqual(PublicationAction.objects.count(), before)
        self.assertNotContains(forbidden, 'value="pub_approve"', status_code=409)

    def test_authority_refresh_revokes_scope_without_rendering_private_desk(self):
        edition = self.edition()
        self.act(edition, "REVIEW", reviewed=True)
        client, page = self.login("publisher")
        directory = self.directory

        class RevokingAuthority(fixtures.Authority):
            def permits(self, **kwargs):
                directory.identities["publisher"] = replace(
                    directory.identities["publisher"], case_keys=frozenset(["other-case"])
                )
                return True

        with override_settings(
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=RevokingAuthority(self.receipt["public_ref"])
        ):
            denied = self.open(client, page)
        self.assertEqual(denied.status_code, 409)
        self.assertNotContains(denied, self.receipt["public_ref"], status_code=409)
        self.assertNotContains(denied, "PRIVATE", status_code=409)
        self.assertFalse(hasattr(denied.wsgi_request, "publication_authorized_case_ref"))
