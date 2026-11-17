"""Occurrence-specific reference navigation with invented fixtures only."""

import json
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_search.reference_cards import ReferenceNotFound, reference_card
from apps.editorial_search.services import search_catalog
from apps.reference_links.resolution import CatalogReadError, SnapshotCatalog
from tests.editorial_search.test_views import SearchMarkup
from tests.research_bridge.test_services import heading_for, verified_fixture


class ReferenceCardTests(SimpleTestCase):
    def setUp(self):
        self.catalog = build_queue_catalog()

    def test_all_reference_hits_resolve_the_exact_occurrence(self):
        for page in range(1, search_catalog(self.catalog, q="SYN", source="reference").pages + 1):
            for hit in search_catalog(self.catalog, q="SYN", source="reference", page=page).hits:
                card = reference_card(
                    self.catalog,
                    hit.case_key,
                    hit.reference_ordinal,
                    hit.revision if hit.reference_origin == "revision" else None,
                )
                self.assertEqual(card.origin, hit.reference_origin)
                self.assertEqual(card.revision, hit.revision)
                self.assertEqual(card.source_sha256, sha256(card.source_text.encode()).hexdigest())

    def test_historical_reference_is_not_replaced_by_current_evidence(self):
        cards = [reference_card(self.catalog, "history", 2, revision) for revision in (1, 9, 11)]
        self.assertEqual([card.revision for card in cards], [1, 9, 11])
        for card in cards:
            self.assertIsNone(card.diagnostic)
            row = next(row for row in self.catalog.rows if row.case.key == "history")
            revision = next(
                entry.revision for entry in row.history if entry.revision.number == card.revision
            )
            self.assertEqual(json.loads(card.source_text), asdict(revision.reference_links[1]))

    def test_invalid_or_ambiguous_occurrence_never_selects_nearest(self):
        for key, ordinal, revision in (
            ("unknown", 1, None),
            ("intake-1", 0, None),
            ("intake-1", True, None),
            ("intake-1", 101, None),
            ("history", 1, 3),
            ("history", 99, 1),
            ("history", 1, 0),
        ):
            with (
                self.subTest(key=key, ordinal=ordinal, revision=revision),
                self.assertRaises(ReferenceNotFound),
            ):
                reference_card(self.catalog, key, ordinal, revision)
        row = next(row for row in self.catalog.rows if row.case.key == "intake-1")
        with self.assertRaises(ReferenceNotFound):
            reference_card(replace(self.catalog, rows=(row, row)), "intake-1", 1)

    def test_duplicate_pointers_keep_separate_ordinal_and_exact_source(self):
        row = next(row for row in self.catalog.rows if len(row.case.references) > 1)
        before = deepcopy(row.case.references)
        first, second = (reference_card(self.catalog, row.case.key, ordinal) for ordinal in (1, 2))
        self.assertEqual((first.ordinal, second.ordinal), (1, 2))
        self.assertEqual(first.source_text, row.case.references[0]["source"]["text"])
        self.assertEqual(second.source_text, row.case.references[1]["source"]["text"])
        self.assertEqual(row.case.references, before)


@override_settings(ALLOWED_HOSTS=["localhost", "remote.invalid"])
class ReferenceCardViewTests(SimpleTestCase):
    def get(self, url=None, **kwargs):
        return self.client.get(
            url or reverse("editorial_search:index"),
            HTTP_HOST="localhost",
            REMOTE_ADDR="127.0.0.1",
            **kwargs,
        )

    def setUp(self):
        self.url = reverse("editorial_search:reference", args=["intake-1", 1])
        self.heading = heading_for(verified_fixture())

    def test_search_does_not_query_catalog_and_card_checks_exact_catalog_on_demand(self):
        with patch("apps.research_bridge.services.DjangoCatalog") as catalog:
            response = self.get(data={"q": "verified", "source": "reference", "batch": "original"})
            catalog.assert_not_called()
            row = response.context["rows"][0]
            self.assertIn(row["reference_url"], SearchMarkup(response.content.decode()).links)
            catalog.return_value = SnapshotCatalog((self.heading,))
            card = self.get(row["reference_url"])
        self.assertEqual(card.status_code, 200)
        self.assertContains(card, "/fiqh/nodes/1?edition=7001")
        self.assertContains(card, self.heading.heading_title)
        self.assertContains(card, self.heading.source_archive_sha256)
        self.assertContains(card, self.heading.source_input_sha256)
        params = parse_qs(urlsplit(card.context["return_url"]).query)
        self.assertEqual(
            params,
            {"q": ["verified"], "source": ["reference"], "batch": ["original"], "page": ["1"]},
        )
        self.assertEqual(self.get(card.context["workbench_url"]).status_code, 200)
        self.assertEqual(self.get(card.context["triage_url"]).status_code, 200)
        self.assertEqual(card["Cache-Control"], "no-store")

    def test_history_cards_preserve_gapped_revisions_without_borrowing_live_evidence(self):
        with patch("apps.editorial_search.views.bridge_reference") as bridge:
            response = self.get(data={"q": "SYN-REMOVE", "source": "reference"})
            for row in response.context["rows"]:
                if row["hit"].reference_origin != "revision":
                    continue
                card = self.get(row["reference_url"])
                self.assertEqual(card.context["card"].revision, row["hit"].revision)
                self.assertIsNone(card.context["triage_url"])
                self.assertContains(card, "لا يُستعار دليل التشخيص الحالي")
                self.assertNotContains(card, "/fiqh/nodes/")
                detail = self.get(card.context["workbench_url"])
                self.assertEqual(detail.context["selected_revision"].number, row["hit"].revision)
            bridge.assert_not_called()

    def test_mismatch_missing_pins_and_unavailable_database_never_show_catalog_link(self):
        unavailable = Mock()
        unavailable.lookup.side_effect = CatalogReadError("private-database-password")
        for catalog in (
            SnapshotCatalog(()),
            SnapshotCatalog((replace(self.heading, printed_page=99),)),
            unavailable,
        ):
            with (
                self.subTest(catalog=catalog),
                patch("apps.research_bridge.services.DjangoCatalog", return_value=catalog),
            ):
                response = self.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "/fiqh/nodes/")
                self.assertNotContains(response, "private-database-password")
                self.assertContains(response, "لا يوجد رابط مكتبة متحقق")
        catalog = build_queue_catalog()
        row = next(row for row in catalog.rows if row.case.key == "intake-1")
        raw = deepcopy(row.case.references[0])
        raw["verified_identity"].pop("source_archive_sha256")
        changed = replace(row, case=replace(row.case, references=(raw,)))
        with (
            patch(
                "apps.editorial_search.views.build_queue_catalog",
                return_value=replace(catalog, rows=(changed,)),
            ),
            patch("apps.research_bridge.services.DjangoCatalog") as live,
        ):
            response = self.get(self.url)
        self.assertNotContains(response, "/fiqh/nodes/")
        live.assert_not_called()

    def test_unresolved_diagnostic_remains_unresolved_without_database_reads(self):
        catalog = build_queue_catalog()
        row = next(
            row
            for row in catalog.rows
            if row.case.references and row.case.references[0]["status"] != "verified"
        )
        with patch("apps.research_bridge.services.DjangoCatalog") as live:
            response = self.get(reverse("editorial_search:reference", args=[row.case.key, 1]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/fiqh/nodes/")
        live.assert_not_called()

    def test_return_link_retains_second_page_and_validated_filters(self):
        first = self.get(data={"q": "SYN", "source": "reference", "batch": "original"})
        second = self.get(first.context["next_url"])
        hit = next(
            row for row in second.context["rows"] if row["hit"].reference_origin == "revision"
        )
        card = self.get(hit["reference_url"])
        returned = self.get(card.context["return_url"])
        self.assertEqual(returned.context["result"], second.context["result"])
        self.assertEqual(returned.context["filters"]["page"], 2)

    def test_original_pointer_is_escaped_with_exact_unicode_and_line_endings(self):
        catalog = build_queue_catalog()
        row = next(row for row in catalog.rows if row.case.key == "intake-1")
        raw = deepcopy(row.case.references[0])
        original = "\n إِحَالَةٌ\r\n<script>اختبار</script> e\u0301 "
        raw["source"]["text"] = original
        changed = replace(row, case=replace(row.case, references=(raw,)))
        with (
            patch(
                "apps.editorial_search.views.build_queue_catalog",
                return_value=replace(catalog, rows=(changed,)),
            ),
            patch("apps.research_bridge.services.DjangoCatalog", return_value=SnapshotCatalog(())),
        ):
            response = self.get(self.url)
        self.assertContains(response, "&#13;")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertIn(original, "".join(SearchMarkup(response.content.decode()).text))

    def test_unknown_identity_invalid_return_and_write_requests_are_rejected(self):
        with patch("apps.editorial_search.views.build_queue_catalog") as build:
            for suffix in (
                "?return=https://remote.invalid",
                "?edition=7001",
                "?q=x&q=y",
                "?page=0",
                "?revision=11",
            ):
                self.assertEqual(self.get(self.url + suffix).status_code, 400)
            for method in ("post", "put", "patch", "delete"):
                self.assertEqual(
                    getattr(self.client, method)(
                        self.url, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                    ).status_code,
                    405,
                )
            self.assertEqual(
                self.client.get(
                    self.url, HTTP_HOST="remote.invalid", REMOTE_ADDR="127.0.0.1"
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(
                    self.url, HTTP_HOST="localhost", REMOTE_ADDR="10.0.0.1"
                ).status_code,
                404,
            )
            with override_settings(FATWA_PRODUCTION=True):
                self.assertEqual(self.get(self.url).status_code, 404)
            build.assert_not_called()
        for args in (("unknown", 1), ("intake-1", 0), ("intake-1", 99)):
            self.assertEqual(
                self.get(reverse("editorial_search:reference", args=args)).status_code, 404
            )
        self.assertEqual(
            self.get(
                reverse("editorial_search:revision_reference", args=["history", 3, 1])
            ).status_code,
            404,
        )
