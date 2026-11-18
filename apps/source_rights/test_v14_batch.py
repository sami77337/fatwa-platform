"""Exact source parity, bounded SQL and collection-final rights failure on PostgreSQL."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.casework.models import Case
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from tests.reference.test_catalog import fixture

from . import batch, services
from .models import RightsAction
from .tests import ENABLED, RightsFixture


@override_settings(**ENABLED)
class BatchReferenceTests(RightsFixture, TransactionTestCase):
    def projection(self, **kwargs):
        return batch.reference_projection_for_locked_case(
            case=Case.objects.get(pk=self.receipt["case_id"]),
            identities=[(self.catalog_id, 2)],
            **kwargs,
        )

    def test_exact_canonical_snapshot_and_no_authority_without_review(self):
        with transaction.atomic(), self.projection() as result:
            self.assertEqual(result, {})
        self.allow()
        with transaction.atomic(), self.projection(usages=("READ", "CITE")) as result:
            self.assertEqual(result[(self.catalog_id, 2)], citations._source(self.catalog_id, 2))

    def test_revoked_during_composition_invalidates_entire_projection(self):
        grant = self.allow()
        with self.assertRaisesMessage(cases.CaseConflict, "current_source_rights_required"):
            with transaction.atomic(), self.projection() as result:
                self.assertEqual(len(result), 1)
                RightsAction.objects.create(
                    revision_id=grant["id"],
                    action="REVOKE",
                    note="Synthetic in-transaction revocation",
                    subject_id="publisher",
                    provider_id=self.directory.provider_id,
                    auth_epoch="epoch-1",
                )

    def test_expiry_during_composition_invalidates_metadata_counts_and_facets(self):
        self.allow()
        future = timezone.now() + timedelta(hours=2)
        with patch.object(services.timezone, "now", wraps=timezone.now) as clock:
            with self.assertRaisesMessage(cases.CaseConflict, "current_source_rights_required"):
                with transaction.atomic(), self.projection() as result:
                    payload = {
                        "count": len(result),
                        "titles": [r["source"]["heading_title"] for r in result.values()],
                    }
                    self.assertEqual(payload["count"], 1)
                    clock.return_value = future

    def test_current_source_changes_and_new_pending_revision_deny(self):
        self.allow()
        self.proposal(number=1)
        with transaction.atomic(), self.projection() as result:
            self.assertEqual(result, {})
        proposal = self.proposal(number=2)
        self.decision(proposal)
        original = batch._catalog
        changed = False

        def catalog(identities):
            values, headings = original(identities)
            if changed:
                for value in values.values():
                    value["source"]["heading_title"] = "مصدر معدل"
            return values, headings

        with patch.object(batch, "_catalog", side_effect=catalog):
            with self.assertRaisesMessage(cases.CaseConflict, "current_source_rights_required"):
                with transaction.atomic(), self.projection() as result:
                    self.assertEqual(len(result), 1)
                    changed = True

    def test_cross_case_missing_registration_and_unknown_use_deny(self):
        self.allow()
        other = cases.intake_case(
            original_question="synthetic other",
            source_event_id="batch-other",
            requester_id="batch-other",
            idempotency_key="batch-other",
            synthetic_fixtures_only=True,
        )
        with (
            transaction.atomic(),
            batch.reference_projection_for_locked_case(
                case=Case.objects.get(pk=other["case_id"]),
                identities=[(self.catalog_id, 2)],
            ) as result,
        ):
            self.assertEqual(result, {})
        for usages in (("PUBLISH",), ("FULL_TEXT",), (), (True,)):
            with (
                self.assertRaises(cases.CaseConflict),
                transaction.atomic(),
                self.projection(usages=usages),
            ):
                self.fail("must deny")

    def test_bounds_transaction_disabled_and_malformed_identity_deny(self):
        with (
            self.assertRaisesMessage(cases.CaseConflict, "rights_batch_transaction_required"),
            self.projection(),
        ):
            self.fail("must deny")
        case = Case.objects.get(pk=self.receipt["case_id"])
        for ids in ([(True, 2)], [(self.catalog_id, 0)], [(1, 2)] * 257, "1:2"):
            with (
                self.assertRaises(cases.CaseConflict),
                transaction.atomic(),
                batch.reference_projection_for_locked_case(case=case, identities=ids),
            ):
                self.fail("must deny")
        with override_settings(FATWA_SOURCE_RIGHTS_ENABLED=False):
            with self.assertRaises(cases.CaseConflict), transaction.atomic(), self.projection():
                self.fail("must deny")

    def test_bulk_query_bound_and_parity_multiple_positions(self):
        rows = list(ReferenceHeading.objects.filter(edition_id=self.catalog_id))
        for row in rows:
            self.allow(row)
        identities = [(row.edition_id, row.source_row_id) for row in rows]
        case = Case.objects.get(pk=self.receipt["case_id"])
        expected = {key: citations._source(*key) for key in identities}
        with transaction.atomic():
            with CaptureQueriesContext(connection) as queries:
                with batch.reference_projection_for_locked_case(
                    case=case, identities=identities
                ) as result:
                    self.assertEqual(result, expected)
            # Two fresh passes, each <=5 catalog +3 ledger reads, plus case lock.
            self.assertLessEqual(len(queries), 17)
        print(f"V14_RIGHTS_BATCH: candidates={len(rows)} sql={len(queries)} fresh_passes=2")

    def test_altered_path_parent_or_edition_never_reuses_old_snapshot(self):
        self.allow()
        original = batch._catalog

        def altered(identities):
            values, headings = original(identities)
            for value in values.values():
                value["source"]["path"][0] = "أصل مختلف"
                value["source_sha256"] = citations._digest(value["source"])
            return values, headings

        with patch.object(batch, "_catalog", side_effect=altered):
            with transaction.atomic(), self.projection() as result:
                self.assertEqual(result, {})

    def test_mutating_yielded_mapping_does_not_mutate_validation_receipt(self):
        self.allow()
        with transaction.atomic(), self.projection() as result:
            result.clear()
        with transaction.atomic(), self.projection() as result:
            self.assertEqual(len(result), 1)

    def test_mixed_editions_have_exact_parity_without_inherited_grants(self):
        spec, rows = fixture()
        spec = replace(spec, source_book_id="622", edition_key="other-synthetic-edition")
        preview = ingest_catalog(spec, rows)
        other_id = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        other = ReferenceHeading.objects.get(edition_id=other_id, source_row_id=2)
        self.allow()
        identities = [(self.catalog_id, 2), (other_id, 2)]
        case = Case.objects.get(pk=self.receipt["case_id"])
        with (
            transaction.atomic(),
            batch.reference_projection_for_locked_case(case=case, identities=identities) as result,
        ):
            self.assertEqual(set(result), {(self.catalog_id, 2)})
        self.allow(other)
        with (
            transaction.atomic(),
            batch.reference_projection_for_locked_case(case=case, identities=identities) as result,
        ):
            self.assertEqual(result, {key: citations._source(*key) for key in identities})
