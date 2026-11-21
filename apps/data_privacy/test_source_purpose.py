"""A public derivative retains its actual publisher across private source readers."""

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.research_library import services as library
from apps.research_library.test_support import FEATURES, LibraryFixture

from . import integration, services
from .test_material_hooks import ExactGrants


@override_settings(**FEATURES)
class OriginalPurposePrivacyTests(ExactGrants, LibraryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.raw = "أصل خاص يستعمله مشتق معلن فقط بإذن نشر مستقل".encode()
        self.material = self.approve(
            self.write(file_bytes=self.raw, filename="private.txt", media_type="text/plain")
        )
        self.privacy_on()
        self.admit("CASE", self.receipt["case_id"], "PUBLISH", actor="publisher")
        self.version_key = self.admit(
            "LIBRARY_VERSION", self.material["version_id"], "PUBLISH", actor="publisher"
        )[0]
        self.publisher = services.staff_principal(
            self.directory, self.directory.resolve("publisher")
        )
        self.source = {**self.common, "subject_id": "other"}

    def test_nested_private_native_actor_cannot_replace_the_explicit_publisher(self):
        with integration.projection(), integration.published_sources(self.publisher):
            actual = library.file_content(**self.source, version_id=self.material["version_id"])
            self.assertEqual(actual["raw"], self.raw)
        source_calls = [
            row
            for row in self.privacy.calls
            if row["action"] != "CLASSIFY" and row["target_kind"] in {"CASE", "LIBRARY_VERSION"}
        ]
        self.assertTrue(source_calls)
        self.assertEqual(
            {(row["subject_id"], row["action"]) for row in source_calls},
            {("publisher", "PUBLISH")},
        )
        with self.assertRaises(services.PrivacyDenied):
            library.file_content(**self.source, version_id=self.material["version_id"])

    def test_current_original_grant_and_native_source_right_remain_independent(self):
        self.authority.denied.add("READ")
        with (
            self.assertRaisesMessage(cases.CaseConflict, "library_action_denied"),
            integration.projection(),
            integration.published_sources(self.publisher),
        ):
            library.file_content(**self.source, version_id=self.material["version_id"])
        self.authority.denied.clear()
        del self.privacy.grants[self.version_key]
        with (
            self.assertRaises(services.PrivacyDenied),
            integration.projection(),
            integration.published_sources(self.publisher),
        ):
            library.file_content(**self.source, version_id=self.material["version_id"])
        self.admit("LIBRARY_VERSION", self.material["version_id"], "PUBLISH", actor="publisher")
        with integration.projection(), integration.published_sources(self.publisher):
            self.assertEqual(
                library.file_content(**self.source, version_id=self.material["version_id"])["raw"],
                self.raw,
            )

    def test_late_native_callback_rechecks_publisher_policy_and_missing_publisher_never_falls_back(
        self,
    ):
        with (
            self.assertRaises(services.PrivacyDenied),
            integration.projection(),
            integration.published_sources(self.publisher),
            library.staff_boundary(**self.source),
        ):
            self.assertEqual(
                library.file_content(**self.source, version_id=self.material["version_id"])["raw"],
                self.raw,
            )
            self.authority.hook = lambda values: self.privacy.grants.pop(self.version_key, None)
        self.authority.hook = None
        with (
            self.assertRaises(services.PrivacyDenied),
            integration.projection(),
            integration.using(self.publisher),
            integration.published_sources(None),
        ):
            integration.source("CASE", self.receipt["case_id"])
