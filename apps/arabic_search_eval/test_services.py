"""New adapter only: real PG + existing case identity and strict source ledger."""

from dataclasses import replace
from datetime import timedelta
from time import perf_counter
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from apps.research_workspace import services as workspace
from apps.research_workspace.rights import Resource
from apps.research_workspace.tests import SETTINGS, ResearchFixture
from apps.source_rights import services as ledger
from apps.source_rights.tests import Authority
from tests.reference.test_catalog import fixture

from . import services


def search_fixture():
    spec, rows = fixture()
    spec = replace(spec, source_book_id="622")
    titles = ["عنوان عام", "عنوان رقم 12", "عنوان رقم 112", "عنوان رقم 12.5", "أَبْوَابُ البَحْث"]
    rows = tuple(
        replace(row, title_original=title) for row, title in zip(rows, titles, strict=True)
    )
    preview = ingest_catalog(spec, rows)
    return ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum).edition_id


@override_settings(
    **SETTINGS, FATWA_SOURCE_RIGHTS_ENABLED=True, FATWA_ARABIC_SEARCH_EVAL_ENABLED=True
)
class AdapterTests(ResearchFixture, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertIn(connection.pg_version // 10000, (17, 18))
        with (
            override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=False),
            patch("apps.knowledge_links.tests.source_fixture", side_effect=search_fixture),
        ):
            super().setUp()
        configured = override_settings(
            FATWA_SOURCE_RIGHTS_ENFORCED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=Authority(self.receipt["public_ref"]),
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def grant(self, row=2, uses=("READ",), number=0):
        heading = ReferenceHeading.objects.get(edition_id=self.catalog_id, source_row_id=row)
        source = ledger.register(**self.common, kind="TOC_METADATA", target_id=heading.pk)
        proposal = ledger.propose(
            **self.common,
            source_id=source["id"],
            expected_number=number,
            uses=list(uses),
            basis="Synthetic explicit rights basis",
            note="Synthetic reviewer fixture",
            ttl_minutes=1,
        )
        ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=proposal["id"],
            action="APPROVE",
            confirmed=True,
            note="Synthetic independent decision",
        )
        return proposal

    def ranked(self, query="رقم ١٢", **kwargs):
        return services.search_reference_titles(
            **{**self.common, "edition_id": self.catalog_id, "query": query, **kwargs}
        )

    def test_real_baseline_vs_digit_and_boundary_ranking_preserves_source_and_open_pins(self):
        for row in (2, 3, 4, 5):
            self.grant(row)
        before = list(ReferenceHeading.objects.values())
        self.assertEqual(
            workspace.search(
                **self.common, kind="REFERENCE", query="رقم ١٢", edition_id=self.catalog_id
            )["results"],
            [],
        )
        old = workspace.search(
            **self.common, kind="REFERENCE", query="رقم 12", edition_id=self.catalog_id
        )["results"]
        self.assertEqual([r["source"]["source_row_id"] for r in old], [2, 3, 4])
        started = perf_counter()
        with CaptureQueriesContext(connection) as captured:
            result = self.ranked()
        print(
            f"ARABIC_SEARCH_SAMPLE authorized=4 selected=1 sql={len(captured)} "
            f"seconds={perf_counter() - started:.4f}"
        )
        self.assertEqual([r["source"]["source_row_id"] for r in result["results"]], [2])
        row = result["results"][0]
        self.assertEqual(row["title"], "عنوان رقم 12")
        opened = workspace.open_resource(**self.common, resource=Resource(**row["resource"]))
        self.assertTrue(opened)
        self.assertEqual(result["coverage"], "BOUNDED_CANDIDATE_WINDOW")
        self.assertEqual(result["candidate_pool_limit"], 20)
        self.assertEqual(self.ranked("ابواب البحث")["results"][0]["source"]["source_row_id"], 5)
        self.assertEqual(before, list(ReferenceHeading.objects.values()))

    def test_unregistered_expired_revoked_metadata_cannot_enter_results(self):
        with self.assertRaises(cases.CaseConflict):
            self.ranked()
        approved = self.grant()
        self.assertEqual(self.ranked("رقم 112")["results"], [])
        future = timezone.now() + timedelta(minutes=2)
        with patch.object(ledger.timezone, "now", return_value=future):
            with self.assertRaises(cases.CaseConflict):
                self.ranked()
        ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=approved["id"],
            action="REVOKE",
            confirmed=True,
            note="Synthetic rights revocation",
        )
        with self.assertRaises(cases.CaseConflict):
            self.ranked()

    def test_scope_and_location_are_preserved(self):
        self.grant()
        self.assertEqual(self.ranked(printed_page=3)["results"], [])
        with self.assertRaises(cases.CaseConflict):
            self.ranked(edition_id=self.catalog_id + 1000)
        with self.assertRaises(cases.CaseConflict):
            self.ranked(subject_id="requester")
        with self.assertRaises(cases.CaseConflict):
            self.ranked(synthetic_fixtures_only=False)
        other = cases.intake_case(
            original_question="Synthetic other case",
            source_event_id="search-other",
            requester_id="search-other",
            idempotency_key="search-other",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.ranked(case_id=other["case_id"], provider=Directory([other["public_ref"]]))

    def test_rights_expiry_during_rank_closes_response_even_if_no_hits_selected(self):
        self.grant()
        self.assertEqual(len(self.ranked()["results"]), 1)
        original = services.rank_titles
        future = timezone.now() + timedelta(minutes=2)
        with patch.object(ledger.timezone, "now", wraps=timezone.now) as clock:

            def expire(*args, **kwargs):
                result = original(*args, **kwargs)
                clock.return_value = future
                return result

            with patch.object(services, "rank_titles", side_effect=expire) as rank:
                for query in ("رقم ١٢", "لا نتيجة"):
                    clock.return_value = timezone.datetime.now(timezone.get_current_timezone())
                    with self.subTest(query=query), self.assertRaises(cases.CaseConflict):
                        self.ranked(query)
                self.assertEqual(rank.call_count, 2)

    def test_policy_revocation_after_ranking_is_rechecked(self):
        self.grant()
        self.assertEqual(len(self.ranked()["results"]), 1)
        original = services.rank_titles

        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            self.rights.denied.add(("REFERENCE", "DISCOVER"))
            return result

        with patch.object(services, "rank_titles", side_effect=revoke) as rank:
            with self.assertRaises(cases.CaseConflict):
                self.ranked()
            rank.assert_called_once()

    def test_disabled_strict_mode_and_invalid_query_do_not_retrieve(self):
        for options in (
            {"FATWA_ARABIC_SEARCH_EVAL_ENABLED": False},
            {"FATWA_SOURCE_RIGHTS_ENFORCED": False},
        ):
            with override_settings(**options), self.assertRaises(cases.CaseConflict):
                self.ranked()
        with patch.object(workspace, "search") as retrieval:
            for query in ("", "ُّ", "!!!", "a" * 81):
                with self.assertRaises(cases.CaseConflict):
                    self.ranked(query)
            retrieval.assert_not_called()
