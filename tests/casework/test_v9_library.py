"""Published-only filters, preserved return context and explicit correction copies."""

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.experimental_publication import services
from apps.experimental_publication import tests as fixtures
from apps.experimental_publication.models import PublicationEdition
from tests.casework.test_http import WEB_SETTINGS, post


@override_settings(FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True)
class LibraryNavigationTests(TransactionTestCase):
    setUp = fixtures.PublicationTests.setUp
    edition = fixtures.PublicationTests.edition
    act = fixtures.PublicationTests.act
    publish = fixtures.PublicationTests.publish
    library = fixtures.PublicationTests.library

    def test_correction_preserves_original_and_needs_new_independent_approval(self):
        source = self.edition(title="أحكام تجريبية", category="الطَّهارة")
        self.publish(source)
        before = dict(PublicationEdition.objects.filter(pk=source["id"]).values().get())
        draft = services.correction_draft(**self.common, edition_id=source["id"])
        self.assertEqual(draft["body"], source["body"])
        revised = self.edition(
            source_edition_id=draft["source_edition_id"], body="تصحيح تحريري تجريبي"
        )
        self.assertEqual(revised["state"], "CANDIDATE")
        self.assertEqual([row["id"] for row in self.library()], [source["id"]])
        self.assertEqual(before, PublicationEdition.objects.filter(pk=source["id"]).values().get())
        self.publish(revised)
        self.assertEqual([row["id"] for row in self.library()], [revised["id"]])
        with self.assertRaisesRegex(cases.CaseConflict, "correction_source_changed"):
            self.edition(source_edition_id=source["id"])
        self.assertEqual(PublicationEdition.objects.count(), 2)
        self.act(revised, "WITHDRAW", "publisher")
        self.assertEqual(self.library(), [])

    @override_settings(**{**WEB_SETTINGS, "ROOT_URLCONF": "config.campaign_urls"})
    def test_filters_exclude_drafts_and_detail_returns_to_same_search(self):
        visible = self.edition(title="أحكام تجريبية", category="الطهارة")
        self.publish(visible)
        hidden = self.edition(title="HIDDEN TITLE", category="PRIVATE CATEGORY")
        common = {k: v for k, v in self.common.items() if k != "case_id"}
        self.assertEqual(
            [p["id"] for p in services.library(**common, query="احكام", category="الطَّهارة")],
            [visible["id"]],
        )
        self.assertEqual(services.library(**common, category="PRIVATE CATEGORY"), [])
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory):
            client = Client(
                enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
            )
            page = client.get("/casework/staff/login/")
            response = post(
                client,
                "/casework/staff/login/",
                {"credential": "synthetic-editor-credential-32-characters"},
                page,
            )
            self.assertEqual(response.status_code, 303)
            page = client.get("/casework/staff/")
            page = post(
                client,
                "/casework/staff/",
                {"action": "pub_library", "query": "احكام", "category": "الطهارة"},
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            self.assertNotContains(page, "PRIVATE CATEGORY")
            self.assertNotContains(page, "HIDDEN TITLE")
            detail = post(
                client,
                "/casework/staff/",
                {
                    "action": "pub_read",
                    "edition_id": visible["id"],
                    "query": "احكام",
                    "category": "الطهارة",
                },
                page,
            )
            self.assertContains(detail, 'name="query" value="احكام"')
            self.assertContains(detail, 'name="category" value="الطهارة"')
            correction = post(
                client,
                "/casework/staff/",
                {
                    "action": "pub_correct",
                    "edition_id": visible["id"],
                    "case_ref": self.receipt["public_ref"],
                },
                detail,
            )
            self.assertContains(correction, 'name="source_edition_id"')
            self.assertContains(correction, "الأصل محفوظ")
            self.assertEqual(PublicationEdition.objects.count(), 2)
            unavailable = post(
                client,
                "/casework/staff/",
                {"action": "pub_read", "edition_id": hidden["id"]},
                correction,
            )
            self.assertEqual(unavailable.status_code, 404)
