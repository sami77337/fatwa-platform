"""Real PostgreSQL ledger and current-use denials; integration hooks are separate."""

import uuid
from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse
from django.test import RequestFactory, TransactionTestCase, override_settings

from apps.casework.models import Case, CaseEvent, CaseEvidence, CaseSource

from . import services
from .catalog import LEVELS, locate
from .models import ClassificationRevision
from .test_support import PrivacyFixture


class ClassificationLedgerTests(PrivacyFixture, TransactionTestCase):
    def read(self, *, action="READ", principal=None):
        return services.require(
            "CASE", self.target.identifier, principal=principal or self.principal(), action=action
        )

    def test_enabled_unclassified_source_fails_before_any_policy_or_content_projection(self):
        self.allow(self.target, "PUBLIC", "READ")
        with self.assertRaisesMessage(services.PrivacyDenied, "privacy_classification_required"):
            self.read()
        self.assertEqual(self.authority.calls, [])
        self.assertFalse(ClassificationRevision.objects.exists())

    def test_four_levels_form_dated_immutable_history_without_changing_source_or_events(self):
        canonical = [
            list(model.objects.values()) for model in (Case, CaseSource, CaseEvidence, CaseEvent)
        ]
        previous = services.ZERO
        for number, level in enumerate(LEVELS, 1):
            result = self.classify(level=level)
            self.assertEqual((result["revision"], result["level"]), (number, level))
            self.assertEqual(result["previous_digest"], previous)
            previous = result["digest"]
            self.assertIsNotNone(result["created_at"])
        self.assertEqual([row.level for row in services.history(self.target)], list(LEVELS))
        self.assertEqual(
            [list(model.objects.values()) for model in (Case, CaseSource, CaseEvidence, CaseEvent)],
            canonical,
        )
        row = ClassificationRevision.objects.last()
        for mutate in (
            lambda: ClassificationRevision.objects.filter(pk=row.pk).update(level="PUBLIC"),
            lambda: ClassificationRevision.objects.filter(pk=row.pk).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                mutate()
        self.assertEqual(ClassificationRevision.objects.count(), 4)

    def test_public_label_does_not_grant_read_search_export_publication_or_ai(self):
        self.classify(level="PUBLIC")
        for action in ("READ", "SEARCH", "EXPORT", "PUBLISH", "AI"):
            with self.subTest(action=action), self.assertRaises(services.PrivacyDenied):
                self.read(action=action)
        for action in ("READ", "SEARCH"):
            self.allow(self.target, "PUBLIC", action)
            self.assertEqual(self.read(action=action)["level"], "PUBLIC")
        for action in ("EXPORT", "PUBLISH", "AI"):
            with self.subTest(action=action), self.assertRaises(services.PrivacyDenied):
                self.read(action=action)

    def test_public_audience_requires_public_label_and_an_independent_current_grant(self):
        public = services.public_principal()
        self.classify(level="RESTRICTED")
        self.allow(self.target, "RESTRICTED", "READ", principal=public)
        with self.assertRaises(services.PrivacyDenied):
            self.read(principal=public)
        self.classify(level="PUBLIC")
        with self.assertRaises(services.PrivacyDenied):
            self.read(principal=public)
        self.allow(self.target, "PUBLIC", "READ", principal=public)
        self.assertEqual(self.read(principal=public)["level"], "PUBLIC")

    def test_public_copy_uses_its_real_publisher_without_granting_original_read(self):
        from . import integration

        self.classify(level="CONFIDENTIAL")
        self.allow(self.target, "CONFIDENTIAL", "PUBLISH")
        with integration.projection(), integration.published_sources(self.principal()):
            self.assertEqual(integration.original_action("READ"), "PUBLISH")
            self.assertEqual(
                integration.source("CASE", self.target.identifier)["level"], "CONFIDENTIAL"
            )
        self.assertEqual(integration.original_action("READ"), "READ")
        for principal in (self.principal(), services.public_principal()):
            with self.assertRaises(services.PrivacyDenied):
                self.read(principal=principal)

    def test_each_staff_read_requires_current_exact_classification_grant(self):
        self.classify()
        self.allow(self.target, "INTERNAL", "READ")
        with self.assertRaises(services.PrivacyDenied):
            self.read()
        key = self.allow(self.target, "CONFIDENTIAL", "READ")
        self.assertEqual(self.read()["revision"], 1)
        del self.authority.grants[key]
        with self.assertRaises(services.PrivacyDenied):
            self.read()
        self.allow(self.target, "CONFIDENTIAL", "READ")
        self.assertEqual(self.read()["revision"], 1)

    def test_policy_missing_disabled_or_removed_application_cannot_bypass_recorded_labels(self):
        self.classify()
        self.allow(self.target, "CONFIDENTIAL", "READ")
        for changes in (
            {"FATWA_DATA_PRIVACY_AUTHORITY": None},
            {"FATWA_DATA_PRIVACY_ENABLED": False},
            {
                "FATWA_DATA_PRIVACY_ENABLED": False,
                "INSTALLED_APPS": [
                    app for app in settings.INSTALLED_APPS if app != "apps.data_privacy"
                ],
            },
        ):
            with self.subTest(changes=tuple(changes)), override_settings(**changes):
                with self.assertRaises(services.PrivacyDenied):
                    self.read()

    def test_default_off_unclassified_records_keep_legacy_behavior_without_writing_labels(self):
        with override_settings(FATWA_DATA_PRIVACY_ENABLED=False):
            self.assertIsNone(self.read())
            with self.assertRaises(services.PrivacyDenied):
                self.classify()
        self.assertFalse(ClassificationRevision.objects.exists())

    def test_stale_or_cross_source_form_cannot_append_or_change_original(self):
        first = self.classify()
        for changes in (
            {"expected_digest": services.ZERO},
            {"expected_source_digest": "f" * 64},
            {"identifier": uuid.uuid4()},
            {"level": "public"},
        ):
            with self.subTest(changes=changes), self.assertRaises(services.cases.CaseConflict):
                self.classify(**changes)
        self.assertEqual(ClassificationRevision.objects.count(), 1)
        self.assertEqual(services.current(self.target).digest, first["digest"])
        self.assertEqual(locate("CASE", self.target.identifier), self.target)

    def test_late_policy_revocation_after_callbacks_discards_a_prepared_projection(self):
        self.classify()
        key = self.allow(self.target, "CONFIDENTIAL", "READ")
        with self.assertRaises(services.PrivacyDenied):
            with services.projection() as guard:
                self.read()
                guard.callbacks()
                del self.authority.grants[key]
        self.allow(self.target, "CONFIDENTIAL", "READ")
        self.assertEqual(self.read()["level"], "CONFIDENTIAL")

    def test_late_identity_or_classification_change_discards_composition(self):
        self.classify()
        self.allow(self.target, "CONFIDENTIAL", "READ")
        original_actor = self.directory.current
        for change in ("identity", "classification"):
            with self.subTest(change=change), self.assertRaises(services.PrivacyDenied):
                with services.projection() as guard:
                    self.read()
                    guard.callbacks()
                    if change == "identity":
                        self.directory.current = replace(original_actor, active=False)
                    else:
                        self.classify(level="RESTRICTED")
            self.directory.current = original_actor
        # The nested classification was rolled back with the refused read.
        self.assertEqual(ClassificationRevision.objects.count(), 1)

    def test_invalid_policy_return_never_becomes_a_grant(self):
        self.classify()
        for value in (True, "allow", {"allowed": True}):
            with (
                self.subTest(value=value),
                patch.object(self.authority, "authorize", return_value=value),
            ):
                with self.assertRaises(services.PrivacyDenied):
                    self.read()

    def test_response_boundary_keeps_authentication_and_external_calls_outside_transactions(self):
        from .integration import PrivacyResponses

        self.classify()
        self.allow(self.target, "CONFIDENTIAL", "READ")

        def endpoint(request):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(self.read()["level"], "CONFIDENTIAL")
            self.assertFalse(connection.in_atomic_block)
            return HttpResponse("authorized synthetic output")

        response = PrivacyResponses(endpoint)(RequestFactory().get("/casework/staff/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"authorized synthetic output")
        self.assertFalse(connection.in_atomic_block)

    def test_response_boundary_discards_output_when_policy_changes_after_short_read(self):
        from .integration import PrivacyResponses

        self.classify()
        key = self.allow(self.target, "CONFIDENTIAL", "READ")

        def endpoint(request):
            self.read()
            self.assertFalse(connection.in_atomic_block)
            del self.authority.grants[key]
            return HttpResponse("private text prepared before revocation")

        response = PrivacyResponses(endpoint)(RequestFactory().get("/casework/staff/"))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"private text", response.content)
        self.assertFalse(connection.in_atomic_block)
