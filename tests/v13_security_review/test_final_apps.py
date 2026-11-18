"""Independent negative V13 checks over canonical synthetic setup only."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.arabic_search_eval import services as search
from apps.arabic_search_eval import test_services as search_fixtures
from apps.casework import services as cases
from apps.casework.models import Case, CaseDecision
from apps.classification_review import services as classification
from apps.classification_review import tests as classification_fixtures
from apps.classification_review.models import ClassificationAction
from apps.composite_delivery import services as delivery
from apps.experimental_publication.models import PublicationEdition
from apps.platform_recovery.integration import MaintenanceUnavailable
from apps.research_workspace import tests as research_fixtures
from apps.source_rights import services as ledger
from apps.source_rights.tests import Authority as RightsAuthority
from apps.timed_citations import services as timed
from apps.timed_citations import tests as timed_fixtures
from apps.timed_citations.models import TimedCitation, TimedCitationAction
from tests.casework import test_v13_timed_bindings as bindings
from tests.v12_security_review import test_maintenance as maintenance_fixtures


@override_settings(**bindings.FEATURES)
class TimedExternalReview(timed_fixtures.Fixture, TransactionTestCase):
    approve = bindings.TimedBindingsTests.approve

    def test_exact_pin_time_human_review_and_new_evidence_deny_downstream_use(self):
        for change in (
            {"version": self.pin["version"] + 1},
            {"metadata_sha256": "0" * 64},
            {"sha256": "f" * 64},
        ):
            with self.subTest(change=change), self.assertRaises(cases.CaseConflict):
                self.propose(source_pin={**self.pin, **change})
        for start, end in ((-1, 20), (0, self.pin["duration_ms"] + 1), (True, 20)):
            with self.subTest(start=start, end=end), self.assertRaises(cases.CaseConflict):
                self.propose(start_ms=start, end_ms=end)
        self.assertEqual(TimedCitation.objects.count(), 0)
        row = self.propose()
        with self.assertRaises(cases.CaseConflict):
            self.approve()
        self.assertFalse(CaseDecision.objects.exists())
        self.confirm(row)
        self.approve()
        self.assertEqual(self.opened(row)["raw"], self.audio["raw"])
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.add_followup(
            token=self.receipt["token"],
            expected_revision=case.revision,
            text="Synthetic changed evidence after locator confirmation",
            synthetic_fixtures_only=True,
        )
        for operation in (
            lambda: self.opened(row),
            lambda: media.staff_read(
                part_id=str(self.part.pk),
                subject_id="editor",
                provider=self.directory,
                synthetic_fixtures_only=True,
            ),
            lambda: delivery.prepare_composite_delivery(**self.common),
        ):
            with self.subTest(operation=operation), self.assertRaises(cases.CaseConflict):
                operation()
        self.assertEqual(TimedCitation.objects.get(pk=row["id"]).snapshot, self.pin)
        self.assertEqual(TimedCitationAction.objects.count(), 1)

    def test_expiry_after_confirmation_insert_rolls_back_human_action(self):
        row = self.propose()
        original = TimedCitationAction.objects.create
        clock = [timezone.now()]
        inserted = []

        def late_expiry(**kwargs):
            result = original(**kwargs)
            inserted.append(result.pk)
            clock[0] = self.rights.valid_until + timedelta(seconds=1)
            return result

        with (
            patch.object(timed.timezone, "now", side_effect=lambda: clock[0]),
            patch.object(TimedCitationAction.objects, "create", side_effect=late_expiry),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.confirm(row)
        self.assertEqual(len(inserted), 1)
        self.assertEqual(TimedCitationAction.objects.count(), 0)
        self.assertEqual(TimedCitation.objects.count(), 1)


@override_settings(
    **{
        **classification_fixtures.FEATURES,
        "FATWA_SOURCE_RIGHTS_ENABLED": True,
        "FATWA_SOURCE_RIGHTS_ENFORCED": False,
    }
)
class ClassificationExternalReview(classification_fixtures.Fixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        configured = override_settings(
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"])
        )
        configured.enable()
        self.addCleanup(configured.disable)
        source = ledger.register(**self.common, kind="TOC_METADATA", target_id=self.heading.pk)
        self.grant = ledger.propose(
            **self.common,
            source_id=source["id"],
            expected_number=0,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
            basis="Synthetic exact source rights",
            note="synthetic",
            ttl_minutes=1,
        )
        ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.grant["id"],
            action="APPROVE",
            confirmed=True,
            note="synthetic",
        )
        strict = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True)
        strict.enable()
        self.addCleanup(strict.disable)

    def test_independence_and_late_expiry_cannot_commit_classification_approval(self):
        row = self.proposal()
        with patch.object(self.classification_authority, "permits", return_value=True):
            with self.assertRaisesMessage(
                cases.CaseConflict, "classification_independent_human_required"
            ):
                self.decision(row, subject_id="editor")
        create = ClassificationAction.objects.create
        clock = [timezone.now()]
        inserted = []

        def expire(**kwargs):
            action = create(**kwargs)
            inserted.append(action.pk)
            clock[0] += timedelta(minutes=2)
            return action

        with (
            patch.object(ledger.timezone, "now", side_effect=lambda: clock[0]),
            patch.object(ClassificationAction.objects, "create", side_effect=expire),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.decision(row)
        self.assertEqual(len(inserted), 1)
        self.assertFalse(ClassificationAction.objects.exists())

    def test_revocation_redacts_audit_and_keeps_human_withdrawal_without_reclassification(self):
        category = PublicationEdition.objects.get(pk=self.edition["id"]).category
        row = self.proposal()
        self.decision(row)
        ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.grant["id"],
            action="REVOKE",
            confirmed=True,
            note="synthetic",
        )
        with self.assertRaises(cases.CaseConflict):
            self.desk()
        audit = self.desk(history=True)
        self.assertEqual(audit["candidates"], [])
        self.assertEqual(audit["existing_category"], "")
        entry = audit["history"][0]
        self.assertEqual((entry["label"], entry["reason"], entry["source"]), ("", "", None))
        self.assertFalse(entry["effective"])
        self.assertNotIn("PRIVATE", str(audit))
        self.decision(row, "WITHDRAW")
        self.assertEqual(PublicationEdition.objects.get(pk=self.edition["id"]).category, category)


@override_settings(
    **research_fixtures.SETTINGS,
    FATWA_SOURCE_RIGHTS_ENABLED=True,
    FATWA_ARABIC_SEARCH_EVAL_ENABLED=True,
)
class SearchExternalReview(research_fixtures.ResearchFixture, TransactionTestCase):
    grant = search_fixtures.AdapterTests.grant
    ranked = search_fixtures.AdapterTests.ranked

    def setUp(self):
        with (
            override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=False),
            patch(
                "apps.knowledge_links.tests.source_fixture",
                side_effect=search_fixtures.search_fixture,
            ),
        ):
            super().setUp()
        configured = override_settings(
            FATWA_SOURCE_RIGHTS_ENFORCED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def test_early_grant_expiry_during_ranking_returns_no_metadata_even_for_no_match(self):
        self.grant(2)
        self.grant(3)
        baseline = self.ranked()
        self.assertEqual(
            (baseline["coverage"], baseline["human_review"], baseline["material"]),
            ("CURRENT_CASE_REGISTERED_TOC", "PENDING", "TOC_METADATA_ONLY"),
        )
        self.assertEqual(baseline["candidate_pool_limit"], 64)
        rank = search.rank_titles
        for query in ("رقم ١٢", "لا نتيجة اصطناعية"):
            clock = [timezone.now()]
            attacks = []

            def expire(*args, **kwargs):
                result = rank(*args, **kwargs)
                attacks.append(1)
                clock[0] += timedelta(minutes=2)
                return result

            with (
                self.subTest(query=query),
                patch.object(ledger.timezone, "now", side_effect=lambda: clock[0]),
                patch.object(search, "rank_titles", side_effect=expire),
            ):
                with self.assertRaises(cases.CaseConflict):
                    self.ranked(query)
            self.assertEqual(attacks, [1])


@override_settings(FATWA_RECOVERY_MAINTENANCE_REQUIRED=False)
class NewAppMaintenanceReview(TransactionTestCase):
    setUp = maintenance_fixtures.MaintenanceP0Tests.setUp
    freeze = maintenance_fixtures.MaintenanceP0Tests.freeze

    def test_new_app_entrypoints_do_not_reach_authority_or_source_when_frozen(self):
        self.freeze()
        operations = (
            (
                timed,
                "_enabled",
                lambda: timed.inspect_source(
                    case_id="unused",
                    kind="ATTACHMENT",
                    source_id="unused",
                    subject_id="editor",
                    provider=None,
                    synthetic_fixtures_only=True,
                ),
            ),
            (
                classification,
                "_enabled",
                lambda: classification.desk(
                    publication_id="unused",
                    subject_id="editor",
                    provider=None,
                    synthetic_fixtures_only=True,
                ),
            ),
            (
                search.workspace,
                "_enabled",
                lambda: search.search_reference_titles(
                    case_id="unused",
                    subject_id="editor",
                    provider=None,
                    query="synthetic",
                    edition_id=1,
                    synthetic_fixtures_only=True,
                ),
            ),
        )
        for module, name, operation in operations:
            with (
                self.subTest(module=module.__name__),
                patch.object(module, name, side_effect=AssertionError("unadmitted source read")),
            ):
                with self.assertRaises(MaintenanceUnavailable):
                    operation()
