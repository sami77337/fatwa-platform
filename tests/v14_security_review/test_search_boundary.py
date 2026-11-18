"""Baseline probe for a multi-result policy change during projection.

This exercises the real strict ledger and source service with an explicit mutable
policy callback, not concurrent SQL revocation or a mock of the rights predicate.
"""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.arabic_search_eval import services as search
from apps.arabic_search_eval.test_services import search_fixture
from apps.casework import services as cases
from apps.research_workspace import tests as research_fixtures
from apps.source_rights.tests import Authority
from tests.v13_security_review import test_final_apps as previous_fixtures


@override_settings(
    **research_fixtures.SETTINGS,
    FATWA_SOURCE_RIGHTS_ENABLED=True,
    FATWA_ARABIC_SEARCH_EVAL_ENABLED=True,
)
class SearchProjectionBoundary(research_fixtures.ResearchFixture, TransactionTestCase):
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

    grant = previous_fixtures.SearchExternalReview.grant
    ranked = previous_fixtures.SearchExternalReview.ranked

    def test_later_result_policy_callback_cannot_leave_revoked_earlier_title(self):
        self.grant(2)
        self.grant(3)
        baseline = self.ranked("عنوان")
        self.assertEqual([r["source"]["source_row_id"] for r in baseline["results"]], [2, 3])
        first, later = [r["resource"]["identifier"] for r in baseline["results"]]
        policy = self.rights.permits
        rank = search.rank_titles
        state = {"ranking_finished": False, "revoked": False, "attacks": 0}

        def finish_ranking(*args, **kwargs):
            result = rank(*args, **kwargs)
            state["ranking_finished"] = True
            return result

        def change_policy(**kwargs):
            identifier = kwargs["resource"].identifier
            if (
                state["ranking_finished"]
                and identifier == later
                and kwargs["action"] == "READ_METADATA"
                and not state["revoked"]
            ):
                state["revoked"] = True
                state["attacks"] += 1
            if state["revoked"] and identifier == first:
                return False
            return policy(**kwargs)

        result = None
        denied = False
        with (
            patch.object(search, "rank_titles", side_effect=finish_ranking),
            patch.object(self.rights, "permits", side_effect=change_policy),
        ):
            try:
                result = self.ranked("عنوان")
            except cases.CaseConflict:
                denied = True
        self.assertEqual(state["attacks"], 1, "The late revocation must actually execute")
        if not denied:
            exposed = [row["resource"]["identifier"] for row in result["results"]]
            self.assertNotIn(first, exposed, "An earlier revoked title survived the later callback")
