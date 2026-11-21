"""Real organizer roles keep privacy through queues and existing publication decisions."""

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.experimental_publication import services as editorial
from apps.experimental_publication.models import PublicationAction
from apps.operational_workspace import publication
from apps.operational_workspace import services as operational
from apps.operational_workspace.publication_test_support import (
    PUBLICATION_FEATURES,
    PublicationFixture,
)

from . import services
from .test_material_hooks import ExactGrants


@override_settings(**PUBLICATION_FEATURES)
class OperationalPrivacyTests(ExactGrants, PublicationFixture, TransactionTestCase):
    classifier = "mufti"

    def setUp(self):
        super().setUp()
        self.privacy_on()

    def admit_case(self, actor):
        return self.admit("CASE", self.target["case_id"], "READ", "SEARCH", actor=actor)

    def admit_publication(self, actor, *actions):
        return self.admit("PUBLICATION", self.edition.pk, *actions, actor=actor)

    def test_unclassified_queue_and_child_sections_are_filtered_before_counts(self):
        with operational.queue_projection(**self.common) as result:
            self.assertEqual(result["rows"], [])
            self.assertEqual(set(result["counts"].values()), {0})
        self.admit_case("operator")
        with operational.queue_projection(**self.common) as result:
            self.assertEqual(result["role"], "ORGANIZER")
            self.assertEqual(len(result["rows"]), 1)
            self.assertEqual(result["counts"]["publication"], 0)
            self.assertNotIn(self.edition.body, repr(result))
        self.admit_publication("operator", "READ")
        with operational.queue_projection(**self.common) as result:
            self.assertEqual(result["counts"]["publication"], 1)
        self.assertEqual(self.immutable_publication_sources(), self.publication_originals)

    def test_organizer_uses_own_grants_and_cannot_borrow_mufti_case_or_publication_read(self):
        self.admit_case("mufti")
        self.admit_publication("mufti", "READ")
        with (
            self.assertRaises(cases.CaseConflict),
            publication.projection(**self.common, case_ref=self.target["public_ref"]),
        ):
            pass
        self.admit_case("operator")
        with publication.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(result["editions"], [])
        self.admit_publication("operator", "READ")
        with publication.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(result["role"], "ORGANIZER")
            self.assertEqual(result["editions"][0]["body"], self.edition.body)
        self.assertEqual(self.directory.identities["operator"].role, "ORGANIZER")

    def test_current_publisher_grants_are_independent_and_withdrawal_does_not_require_read(self):
        self.admit_case("operator")
        self.admit_publication("operator", "READ")
        with self.assertRaises(services.PrivacyDenied):
            self.publication_decide()
        self.admit("ANSWER", self.edition.answer_id, "PUBLISH", actor="operator")
        self.publication_decide()
        self.admit_case("admin")
        keys = self.admit_publication("admin", "READ", "PUBLISH")
        keys += self.admit("ANSWER", self.edition.answer_id, "PUBLISH", actor="admin")
        self.assertEqual(
            self.publication_decide(subject="admin", action="APPROVE")["editions"][0]["state"],
            "PUBLISHED",
        )
        for key in keys:
            del self.privacy.grants[key]
        result = self.publication_decide(subject="admin", action="WITHDRAW")
        self.assertEqual(result["editions"], [])
        self.assertNotIn(self.edition.body, repr(result))
        self.assertTrue(
            PublicationAction.objects.filter(
                edition=self.edition, action="WITHDRAW", subject_id="admin"
            ).exists()
        )
        self.assertEqual(self.immutable_publication_sources(), self.publication_originals)

    def test_last_operational_callback_can_revoke_privacy_and_restore_positive_projection(self):
        self.admit_case("operator")
        key = self.admit_publication("operator", "READ")[0]
        with (
            self.assertRaises(services.PrivacyDenied),
            publication.projection(**self.common, case_ref=self.target["public_ref"]) as result,
        ):
            self.assertEqual(len(result["editions"]), 1)
            self.publication_domain.hook = lambda values: self.privacy.grants.pop(key, None)
        self.publication_domain.hook = None
        self.admit_publication("operator", "READ")
        with publication.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(len(result["editions"]), 1)

    def test_mufti_withdraw_returns_only_receipt_when_copy_read_is_not_granted(self):
        self.admit_case("mufti")
        result = editorial.act(
            case_id=self.target["case_id"],
            edition_id=self.edition.pk,
            subject_id="mufti",
            provider=self.directory,
            action="WITHDRAW",
            synthetic_fixtures_only=True,
        )
        self.assertEqual(
            result,
            {"id": str(self.edition.pk), "number": self.edition.number, "state": "WITHDRAWN"},
        )
        self.assertTrue(
            PublicationAction.objects.filter(edition=self.edition, action="WITHDRAW").exists()
        )
