"""Independent late ledger mutation and policy-version repair challenges."""

from unittest.mock import patch

from apps.casework import services as cases
from apps.source_rights import services as ledger
from tests.v14_security_review import test_search_boundary as fixture


class SearchRepairBoundary(fixture.SearchProjectionBoundary):
    # Run explicit methods, not the inherited original reproducer twice.
    def test_ledger_revocation_during_final_policy_pass_closes_response(self):
        approved = self.grant(2)
        self.grant(3)
        policy = self.rights.permits
        visits = []
        revoked = []

        def revoke(**kwargs):
            if (
                kwargs["resource"].identifier == f"{self.catalog_id}:3"
                and kwargs["action"] == "READ_METADATA"
            ):
                visits.append(1)
                if len(visits) == 3:
                    ledger.review(
                        **{**self.common, "subject_id": "publisher"},
                        revision_id=approved["id"],
                        action="REVOKE",
                        confirmed=True,
                        note="Independent synthetic late ledger revocation",
                    )
                    revoked.append(1)
            return policy(**kwargs)

        denied = False
        result = None
        with patch.object(self.rights, "permits", side_effect=revoke):
            try:
                result = self.ranked("عنوان", page_size=1)
            except cases.CaseConflict:
                denied = True
        self.assertEqual(revoked, [1], "The actual ledger review must execute")
        self.assertTrue(denied, f"Stale projection escaped after ledger revocation: {result}")

    def test_missing_malformed_and_changed_policy_epoch_deny(self):
        self.grant(2)
        for value in (None, "", True, 5, "x" * 1001):
            with (
                self.subTest(epoch=value),
                patch.object(self.rights, "projection_epoch", return_value=value),
            ):
                with self.assertRaises(cases.CaseConflict):
                    self.ranked("عنوان")
        with patch.object(self.rights, "projection_epoch", side_effect=["before", "after"]):
            with self.assertRaisesMessage(cases.CaseConflict, "research_policy_changed"):
                self.ranked("عنوان")

    def test_counts_pages_pins_and_query_sample_only_include_readable_sources(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.case_citations import services as citations

        for row in (2, 3, 4, 5):
            self.grant(row)
        with CaptureQueriesContext(connection) as captured:
            all_rows = self.ranked("عنوان", page_size=1, page=2)
        print(f"EXTERNAL_V14_SQL four_authorized={len(captured)}")
        self.assertLess(len(captured), 70)
        self.assertEqual(all_rows["total"], 3)
        self.assertEqual(
            (all_rows["pages"], all_rows["next_page"], all_rows["previous_page"]), (3, 3, 1)
        )
        self.assertEqual(sum(item["count"] for item in all_rows["facets"]), 3)
        row = all_rows["results"][0]
        original = citations._source(self.catalog_id, row["source"]["source_row_id"])
        self.assertEqual(row["source"], original["source"])
        self.assertEqual(row["resource"]["sha256"], original["source_sha256"])
        self.assertNotIn("_rights_revision", row)
        self.assertEqual(all_rows["human_review"], "PENDING")

    def test_expiry_at_final_identity_check_denies_counts_even_for_empty_page(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.research_workspace import services as workspace

        self.grant(2)
        self.grant(3)
        original = workspace._recheck
        for query, page in (("عنوان", 2), ("لا نتيجة", 1)):
            clock = [timezone.now()]
            attacks = []

            def expire(*args, **kwargs):
                original(*args, **kwargs)
                clock[0] += timedelta(minutes=2)
                attacks.append(1)

            with (
                self.subTest(query=query, page=page),
                patch.object(ledger.timezone, "now", side_effect=lambda: clock[0]),
                patch.object(workspace, "_recheck", side_effect=expire),
            ):
                with self.assertRaises(cases.CaseConflict):
                    self.ranked(query, page=page, page_size=1)
            self.assertEqual(attacks, [1])

    def test_catalog_version_mutation_is_rejected_before_projection(self):
        from django.db import IntegrityError

        from apps.arabic_search_eval import services as search
        from apps.reference.models import ReferenceEdition

        self.grant(2)
        rank = search.rank_titles
        attacks = []

        def change(*args, **kwargs):
            hits = rank(*args, **kwargs)
            attacks.append(1)
            ReferenceEdition.objects.filter(pk=self.catalog_id).update(source_input_sha256="f" * 64)
            return hits

        with patch.object(search, "rank_titles", side_effect=change):
            with self.assertRaisesMessage(IntegrityError, "Source catalog snapshots are immutable"):
                self.ranked("عنوان")
        self.assertEqual(attacks, [1])

        self.assertEqual(
            ReferenceEdition.objects.get(pk=self.catalog_id).source_input_sha256, "b" * 64
        )
