"""Late authority callbacks cannot mutate the ledger behind projected metadata."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.arabic_search_eval.test_services import search_fixture
from apps.casework import services as cases
from apps.research_workspace import services as workspace
from apps.research_workspace import tests as research_fixtures
from apps.source_rights import services as ledger
from apps.source_rights.tests import Authority
from tests.v13_security_review import test_final_apps as prior


@override_settings(
    **research_fixtures.SETTINGS,
    FATWA_SOURCE_RIGHTS_ENABLED=True,
    FATWA_ARABIC_SEARCH_EVAL_ENABLED=True,
)
class FinalSearchLedgerTests(research_fixtures.ResearchFixture, TransactionTestCase):
    grant = prior.SearchExternalReview.grant
    ranked = prior.SearchExternalReview.ranked

    def setUp(self):
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
        self.approved = self.grant(2)
        self.grant(3)
        self.revocations = 0

    def revoke(self):
        ledger.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.approved["id"],
            action="REVOKE",
            confirmed=True,
            note="Synthetic late authority callback",
        )
        self.revocations += 1

    def test_final_identity_callback_cannot_leave_stale_counts_or_page_hints(self):
        original = workspace._recheck

        def change(*args, **kwargs):
            original(*args, **kwargs)
            self.revoke()

        with patch.object(workspace, "_recheck", side_effect=change):
            with self.assertRaises(cases.CaseConflict):
                self.ranked("عنوان", page_size=1)
        self.assertEqual(self.revocations, 1)

    def test_final_epoch_callback_cannot_mutate_ledger_after_last_check(self):
        # Epoch callbacks are specified as side-effect-free. Even a broken
        # configured callback cannot bypass the final independent ledger veto.
        original = self.rights.projection_epoch
        calls = []

        def change():
            calls.append(1)
            if len(calls) == 2:
                self.revoke()
            return original()

        with patch.object(self.rights, "projection_epoch", side_effect=change):
            with self.assertRaises(cases.CaseConflict):
                self.ranked("عنوان", page_size=1, page=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.revocations, 1)
