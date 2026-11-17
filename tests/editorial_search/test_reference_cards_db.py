"""Real PostgreSQL proof for search -> occurrence -> pinned catalog, synthetic only."""

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.reference.models import ReferenceEdition, ReferenceHeading, ReferenceWork
from apps.reference.normalization import normalize_title
from tests.research_bridge.test_services import heading_for, verified_fixture


@override_settings(ALLOWED_HOSTS=["localhost"])
class ReferenceCardDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        if connection.vendor != "postgresql" or not 170000 <= connection.pg_version < 190000:
            raise AssertionError("Real PostgreSQL 17 or 18 required")
        cls.heading = heading_for(verified_fixture())
        work = ReferenceWork.objects.create(
            source_namespace=cls.heading.source_namespace,
            source_book_id=cls.heading.source_book_id,
            title_original=cls.heading.work_title,
            madhhab="اختبار اصطناعي",
        )
        cls.edition = ReferenceEdition.objects.create(
            pk=cls.heading.edition_id,
            work=work,
            edition_key=cls.heading.edition_key,
            title="طبعة اصطناعية لاختبار بطاقة الإحالة",
            publisher="ناشر اصطناعي",
            source_archive_sha256=cls.heading.source_archive_sha256,
            source_input_sha256=cls.heading.source_input_sha256,
            input_name="search-reference-card-synthetic-v1",
            ingest_checksum="c" * 64,
            heading_count=1,
            root_count=1,
            max_depth=1,
        )
        ReferenceHeading.objects.create(
            edition=cls.edition,
            source_id="synthetic-search-card-root",
            source_row_id=cls.heading.source_row_id,
            source_order=1,
            position=1,
            depth=1,
            source_page_id=7001,
            source_part=cls.heading.printed_part,
            source_page_number=cls.heading.printed_page,
            title_original=cls.heading.heading_title,
            title_normalized=normalize_title(cls.heading.heading_title),
        )

    def get(self, url, data=None):
        return self.client.get(url, data, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")

    def test_search_card_and_library_link_follow_real_read_only_catalog(self):
        with self.assertNumQueries(0):
            response = self.get("/dev/editorial-search", {"q": "verified", "source": "reference"})
        row = response.context["rows"][0]
        with CaptureQueriesContext(connection) as queries:
            card = self.get(row["reference_url"])
        self.assertEqual(card.status_code, 200)
        self.assertEqual(card.context["bridge"].status, "verified")
        self.assertTrue(all(query["sql"].lstrip().startswith("SELECT") for query in queries))
        self.assertLessEqual(len(queries), 4)
        linked = self.get(card.context["bridge"].catalog_url)
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.context["edition"]["id"], self.edition.pk)
        self.assertEqual(linked.context["node"]["id"], self.heading.source_row_id)
        self.assertEqual(linked.context["node"]["title"], self.heading.heading_title)
        self.assertEqual(linked.context["node"]["page"], self.heading.printed_page)

    def test_existing_edition_with_absent_exact_row_does_not_offer_similar_heading(self):
        # Existing intake-7 occurrence 1 asserts row 2, while this fixture only has row 1.
        card = self.get("/dev/editorial-search/references/intake-7/diagnostics/1")
        self.assertEqual(card.status_code, 200)
        self.assertEqual(card.context["bridge"].status, "unverified")
        self.assertIsNone(card.context["bridge"].catalog_url)
        self.assertNotContains(card, "/fiqh/nodes/")
