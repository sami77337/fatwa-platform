"""Batch parity, growth, authorization aggregation and SEC14 projection regressions."""

from dataclasses import replace
from time import perf_counter
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.reference.ingest import ingest_catalog
from apps.reference.records import HeadingRecord
from apps.research_workspace import reference_batch
from apps.research_workspace.rights import ResearchRights
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from apps.research_workspace.tests import SETTINGS, ResearchFixture
from apps.source_rights import services as ledger
from apps.source_rights.models import SourceVersion
from apps.source_rights.tests import Authority
from tests.reference.test_catalog import fixture

from . import services
from . import test_services as fixtures


def large_fixture():
    spec, _ = fixture()
    spec = replace(
        spec, source_book_id="622", expected_rows=30, expected_roots=1, expected_max_depth=2
    )
    rows = [
        HeadingRecord(
            f"synthetic-{i}",
            i,
            None if i == 1 else 1,
            i,
            i,
            1 if i == 1 else 2,
            i,
            "أ" if i <= 20 else "ب",
            i,
            f"عنوان رقم {i}",
        )
        for i in range(1, 31)
    ]
    draft = ingest_catalog(spec, rows)
    return ingest_catalog(spec, rows, dry_run=False, expected_checksum=draft.checksum).edition_id


@override_settings(
    **SETTINGS, FATWA_SOURCE_RIGHTS_ENABLED=True, FATWA_ARABIC_SEARCH_EVAL_ENABLED=True
)
class BatchTests(ResearchFixture, TransactionTestCase):
    def test_internal_batch_requires_current_maintenance_admission(self):
        from apps.platform_recovery.integration import MaintenanceUnavailable

        with override_settings(FATWA_RECOVERY_MAINTENANCE_REQUIRED=True):
            with self.assertRaises(MaintenanceUnavailable):
                reference_batch.read_locked(
                    case=None, actor=None, provider=None, edition_id=self.catalog_id
                )

    def setUp(self):
        with (
            override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=False),
            patch("apps.knowledge_links.tests.source_fixture", side_effect=large_fixture),
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

    grant = fixtures.AdapterTests.grant
    ranked = fixtures.AdapterTests.ranked

    def test_batch_query_count_does_not_grow_with_24_sources_and_pages_reach_past_20(self):
        self.grant(2)
        with CaptureQueriesContext(connection) as single:
            self.ranked("عنوان")
        for i in range(3, 26):
            self.grant(i)
        start = perf_counter()
        with CaptureQueriesContext(connection) as many:
            first = self.ranked("عنوان")
        print(
            f"V14_BATCH candidates=24 sql={len(many)} single_sql={len(single)} seconds={perf_counter() - start:.4f}"
        )
        self.assertLessEqual(len(many), len(single) + 2)
        self.assertLess(len(many), 70)
        self.assertEqual(first["total"], 24)
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual(first["next_page"], 2)
        second = self.ranked("عنوان", page=2)
        self.assertEqual(
            [r["source"]["source_row_id"] for r in second["results"]], list(range(22, 26))
        )
        self.assertEqual(
            second["facets"],
            [{"printed_part": "أ", "count": 19}, {"printed_part": "ب", "count": 5}],
        )
        self.assertIsNone(second["next_page"])
        self.assertEqual(self.ranked("رقم ٢٥")["results"][0]["source"]["source_row_id"], 25)
        for r in second["results"]:
            original = citations._source(self.catalog_id, r["source"]["source_row_id"])
            self.assertEqual(r["source"], original["source"])
            self.assertEqual(r["resource"]["sha256"], original["source_sha256"])
            self.assertNotIn("_rights_revision", r)

    def test_latest_pending_rejected_and_non_read_never_affect_counts_or_facets(self):
        self.grant(2)
        self.grant(21, uses=("CITE",))
        self.grant(22)
        source = SourceVersion.objects.get(heading__source_row_id=22)
        pending = ledger.propose(
            **self.common,
            source_id=str(source.pk),
            expected_number=1,
            uses=["READ"],
            basis="Synthetic restriction review",
            note="Pending replacement",
            ttl_minutes=10,
        )
        for state in ("PENDING", "REJECT"):
            if state == "REJECT":
                ledger.review(
                    **{**self.common, "subject_id": "publisher"},
                    revision_id=pending["id"],
                    action="REJECT",
                    confirmed=True,
                    note="Synthetic rejection",
                )
            result = self.ranked("عنوان")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["facets"], [{"printed_part": "أ", "count": 1}])
            self.assertEqual(result["pages"], 1)
        self.assertEqual(self.ranked("رقم 22")["total"], 0)

    def test_later_callback_revocation_is_caught_at_collection_boundary(self):
        self.grant(2)
        self.grant(3)
        original = services.rank_titles
        policy = self.rights.permits
        state = {"ranked": False, "revoked": False, "attacks": 0}

        def rank(*args, **kwargs):
            hits = original(*args, **kwargs)
            state["ranked"] = True
            return hits

        def permits(**kw):
            ident = kw["resource"].identifier
            if (
                state["ranked"]
                and ident == f"{self.catalog_id}:3"
                and kw["action"] == "READ_METADATA"
                and not state["revoked"]
            ):
                state["revoked"] = True
                state["attacks"] += 1
            return False if state["revoked"] and ident == f"{self.catalog_id}:2" else policy(**kw)

        with (
            patch.object(services, "rank_titles", side_effect=rank),
            patch.object(self.rights, "permits", side_effect=permits),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.ranked("عنوان")
        self.assertEqual(state["attacks"], 1)

    def test_final_pass_policy_epoch_change_blocks_already_checked_earlier_row(self):
        self.grant(2)
        self.grant(3)
        policy = self.rights.permits
        visits = 0

        def permits(**kw):
            nonlocal visits
            if (
                kw["resource"].identifier == f"{self.catalog_id}:3"
                and kw["action"] == "READ_METADATA"
            ):
                visits += 1
                if visits == 3:
                    self.rights.denied.add(("REFERENCE", "DISCOVER"))
            return policy(**kw)

        with patch.object(self.rights, "permits", side_effect=permits):
            with self.assertRaises(cases.CaseConflict):
                self.ranked("عنوان")
        self.assertEqual(visits, 3)

    def test_real_ledger_revocation_after_rank_reloads_before_aggregates(self):
        approved = self.grant(2)
        self.grant(21)
        original = services.rank_titles

        def revoke(*args, **kwargs):
            hits = original(*args, **kwargs)
            ledger.review(
                **{**self.common, "subject_id": "publisher"},
                revision_id=approved["id"],
                action="REVOKE",
                confirmed=True,
                note="Synthetic boundary revocation",
            )
            return hits

        with patch.object(services, "rank_titles", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.ranked("عنوان", page=2)
        # Same-connection callback mutation rolls back with the denied projection.
        # This is not evidence of a concurrent committed SQL revocation.
        self.assertEqual(self.ranked("عنوان")["total"], 2)
        ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=approved["id"],
            action="REVOKE",
            confirmed=True,
            note="Synthetic separate committed revocation",
        )
        self.assertEqual(self.ranked("عنوان")["total"], 1)

    def test_unknown_epoch_fails_closed_and_exact_builtin_adapter_remains_strict(self):
        class Unversioned(ResearchRights):
            def permits(self, **kw):
                return True

        self.grant(2)
        with override_settings(FATWA_RESEARCH_WORKSPACE_RIGHTS=Unversioned()):
            with self.assertRaisesMessage(cases.CaseConflict, "research_policy_snapshot_required"):
                self.ranked("عنوان")
        with override_settings(FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter()):
            self.assertEqual(self.ranked("عنوان")["total"], 1)
            self.assertEqual(self.ranked("رقم 3")["total"], 0)
        original = reference_batch._source

        def altered(heading):
            source = original(heading)
            source["source"]["heading_title"] = "Synthetic altered"
            return source

        with patch.object(reference_batch, "_source", side_effect=altered):
            with self.assertRaises(cases.CaseConflict):
                self.ranked("عنوان")
