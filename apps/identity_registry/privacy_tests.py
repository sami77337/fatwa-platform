"""Names, groups and counts retain the classification of their actual origins."""

from django.test import TransactionTestCase, override_settings

from apps.ai_gateway.privacy_test_support import ClassifiedSources
from apps.data_privacy.services import PrivacyDenied
from apps.source_case_intake.models import EvidenceBinding

from . import services
from .models import IdentityObservation, PlatformIdentity
from .test_support import FEATURES, RegistryFixture


@override_settings(**FEATURES)
class IdentityRegistryPrivacyTests(RegistryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.privacy = ClassifiedSources(self, self.directory, "editor")
        self.receipt_id = EvidenceBinding.objects.get(case_id=self.receipt["case_id"]).receipt_id

    def classify_origin(self, *, actions=("READ", "SEARCH")):
        self.privacy.classify("CASE", self.receipt["case_id"], actions=actions)
        self.privacy.classify("SOURCE_RECEIPT", self.receipt_id, actions=actions)

    def test_case_and_original_receipt_are_required_before_name_capture(self):
        with self.assertRaises(PrivacyDenied):
            self.capture()
        self.privacy.classify("CASE", self.receipt["case_id"], actions=("READ", "SEARCH"))
        with self.assertRaises(PrivacyDenied):
            self.capture()
        self.assertEqual(PlatformIdentity.objects.count(), 0)
        self.assertEqual(IdentityObservation.objects.count(), 0)
        self.privacy.classify("SOURCE_RECEIPT", self.receipt_id, actions=("READ", "SEARCH"))
        self.capture()
        self.assertEqual(PlatformIdentity.objects.count(), 1)

    def test_read_grants_do_not_grant_search_or_hidden_names_and_group_counts(self):
        self.classify_origin()
        self.capture()
        self.assertEqual(len(self.state()["identities"]), 1)
        self.privacy.authority.grants = {
            key: value
            for key, value in self.privacy.authority.grants.items()
            if dict(key)["action"] != "SEARCH"
        }
        result = self.state()
        self.assertEqual(result["identities"], [])
        self.assertEqual(result["people"], [])

    def test_late_classification_revocation_rolls_back_identity_capture(self):
        self.classify_origin()
        command = self.command()

        def withdraw(values):
            if values["action"] == "CAPTURE" and PlatformIdentity.objects.exists():
                self.privacy.authority.grants.clear()

        self.authority.hook = withdraw
        with self.assertRaises(PrivacyDenied):
            services.capture(**command)
        self.assertEqual(PlatformIdentity.objects.count(), 0)
        self.assertEqual(IdentityObservation.objects.count(), 0)
