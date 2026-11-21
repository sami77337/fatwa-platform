"""Enforced canonical source ledger, independent review and final expiry boundaries."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.source_rights import services as rights
from apps.source_rights.models import RightsRevision
from apps.source_rights.tests import Authority as RightsAuthority

from . import policy
from .test_support import FEATURES, SearchFixture


@override_settings(
    **{**FEATURES, "FATWA_SOURCE_RIGHTS_ENABLED": True, "FATWA_SOURCE_RIGHTS_ENFORCED": True}
)
class CanonicalSearchRightsTests(SearchFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        configured = override_settings(
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"])
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.link, self.entry = self.transcript()
        self.source = rights.register(
            **self.common, kind="PRIVATE_TRANSCRIPT", target_id=self.link["link_id"]
        )

    def allow(self):
        proposal = rights.propose(
            **self.common,
            source_id=self.source["id"],
            expected_number=0,
            uses=["READ"],
            basis="Independently reviewed synthetic source",
            note="No publication or other usage",
            ttl_minutes=1,
        )
        rights.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=proposal["id"],
            action="APPROVE",
            confirmed=True,
            note="Explicit synthetic source review",
        )
        return proposal

    def test_broad_custom_policy_cannot_bypass_current_independently_reviewed_ledger(self):
        self.build()
        self.assertEqual(self.search("لاختبار حفظ النص")["results"], [])
        self.assertEqual(self.search("المعاملات")["total"], 1)
        proposal = self.allow()
        self.assertEqual(self.search("لاختبار حفظ النص")["indexes"][0]["state"], "STALE")
        self.build()
        self.assertEqual(self.search("لاختبار حفظ النص")["total"], 1)
        rights.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=proposal["id"],
            action="REVOKE",
            confirmed=True,
            note="Current source use withdrawn",
        )
        self.assertEqual(self.search("لاختبار حفظ النص")["results"], [])
        self.assertEqual(self.search("المعاملات")["total"], 1)

    def test_last_identity_callback_cannot_remove_consumed_ledger_authority(self):
        self.allow()
        self.build()
        self.authority.calls.clear()
        original = self.directory.resolve

        def revoke(subject):
            actor = original(subject)
            if len([row for row in self.authority.calls if row["action"] == "SEARCH"]) == 2:
                settings.FATWA_SOURCE_RIGHTS_AUTHORITY = None
            return actor

        self.directory.resolve = revoke
        with self.assertRaises(cases.CaseConflict):
            self.search("لاختبار حفظ النص")

    def test_expiry_after_last_source_callback_rejects_whole_projection(self):
        proposal = self.allow()
        self.build()
        deadline = RightsRevision.objects.get(pk=proposal["id"]).valid_until
        clock = [timezone.now()]
        self.authority.calls.clear()
        original = self.directory.resolve

        def expire(subject):
            actor = original(subject)
            if len([row for row in self.authority.calls if row["action"] == "SEARCH"]) == 2:
                clock[0] = deadline + timedelta(seconds=1)
            return actor

        self.directory.resolve = expire
        with patch.object(policy.timezone, "now", side_effect=lambda: clock[0]):
            with self.assertRaises(cases.CaseConflict):
                self.search("لاختبار حفظ النص")
        self.assertGreater(self.directory.identities["editor"].valid_until, clock[0])

    def test_expired_source_has_no_search_count_or_hidden_followup_copy(self):
        proposal = self.allow()
        self.build()
        deadline = RightsRevision.objects.get(pk=proposal["id"]).valid_until
        with patch.object(policy.timezone, "now", return_value=deadline + timedelta(seconds=1)):
            self.assertEqual(self.search("لاختبار حفظ النص")["total"], 0)
            self.assertEqual(self.search("المعاملات")["total"], 1)

    def test_final_boolean_to_integer_gate_change_cannot_evade_snapshot(self):
        self.allow()
        self.build()
        original = self.directory.resolve
        for setting in ("FATWA_SOURCE_RIGHTS_ENABLED", "FATWA_SOURCE_RIGHTS_ENFORCED"):
            self.authority.calls.clear()

            def malformed(subject):
                actor = original(subject)
                if len([row for row in self.authority.calls if row["action"] == "SEARCH"]) == 2:
                    setattr(settings, setting, 1)
                return actor

            with override_settings(**{setting: True}):
                self.directory.resolve = malformed
                with self.assertRaises(cases.CaseConflict):
                    self.search("لاختبار حفظ النص")
            self.directory.resolve = original
