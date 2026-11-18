"""V14 closed simulation: canonical editions, exact provenance and independent decisions."""

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication import services as publications
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.knowledge_links.tests import Fixture as KnowledgeFixture
from apps.platform_recovery import maintenance
from apps.platform_recovery.integration import MaintenanceUnavailable
from apps.private_media.filesystem import FileSystemStorage
from apps.source_rights import services as rights
from apps.source_rights.tests import Authority as RightsAuthority

from . import editorial
from .authority import EditorialSimulationPolicy
from .models import EditorialBinding
from .tests import FEATURES, Fixture


class SimulationPolicy(EditorialSimulationPolicy):
    policy_id = "synthetic-v14-classification-editorial-v1"

    def __init__(self, ref, revision_id):
        self.ref, self.revision_id = ref, revision_id

    def permits(self, **kwargs):
        return (
            kwargs["case_ref"] == self.ref
            and kwargs["revision_id"] == self.revision_id
            and kwargs["auth_epoch"] == "epoch-1"
            and kwargs["action"] in {"INSPECT", "PREPARE", "REVIEW", "APPROVE"}
            and kwargs["subject_id"] in {"editor", "publisher", "other"}
        )


class PublishingAuthority(PublicationAuthority):
    def permits(self, **kwargs):
        return (
            kwargs["case_ref"] == self.ref
            and kwargs["auth_epoch"] == "epoch-1"
            and kwargs["subject_id"] in {"publisher", "other"}
        )


class EditorialFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.classification = self.proposal()
        self.decision(self.classification)
        self.simulation_policy = SimulationPolicy(
            self.receipt["public_ref"], self.classification["id"]
        )
        temporary = tempfile.TemporaryDirectory(prefix="v14-classification-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        storage = FileSystemStorage(root / "private", synthetic_fixtures_only=True)
        self.control = root / "control"
        self.control.mkdir(mode=0o700)
        maintenance.initialize(root=self.control, storage=storage, synthetic_fixtures_only=True)
        policy = override_settings(
            FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED=True,
            FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_POLICY=self.simulation_policy,
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=PublishingAuthority(
                self.receipt["public_ref"]
            ),
            FATWA_SOURCE_RIGHTS_ENABLED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=str(self.control),
            FATWA_PRIVATE_MEDIA_STORAGE=storage,
        )
        policy.enable()
        self.addCleanup(policy.disable)
        self.rights_source = rights.register(
            **self.common, kind="TOC_METADATA", target_id=self.heading.pk
        )
        self.grant = rights.propose(
            **self.common,
            source_id=self.rights_source["id"],
            expected_number=0,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
            basis="Synthetic reviewed source licence",
            note="synthetic",
            ttl_minutes=1,
        )
        rights.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.grant["id"],
            action="APPROVE",
            confirmed=True,
            note="synthetic independent rights",
        )
        strict = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True)
        strict.enable()
        self.addCleanup(strict.disable)

    def prepare(self, **kwargs):
        case = Case.objects.get(pk=self.receipt["case_id"])
        args = dict(
            self.access,
            revision_id=self.classification["id"],
            confirmed=True,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        return editorial.prepare_edition(**{**args, **kwargs})

    def editorial_action(self, binding, action="REVIEW", **kwargs):
        args = dict(
            self.access,
            binding_id=binding["binding_id"],
            action=action,
            confirmed=True,
            subject_id="other" if action == "APPROVE" else "editor",
        )
        return editorial.act(**{**args, **kwargs})

    def inspect_binding(self, binding, **kwargs):
        return editorial.inspect(**{**self.access, "binding_id": binding["binding_id"], **kwargs})

    def library(self):
        return publications.library(
            **{k: v for k, v in self.access.items() if k != "publication_id"}
        )


@override_settings(**FEATURES)
class EditorialTests(EditorialFixture, TransactionTestCase):
    def test_candidate_links_exact_approved_classification_without_publishing(self):
        before = self.library()
        source = PublicationEdition.objects.get(pk=self.edition["id"])
        binding = self.prepare()
        target = PublicationEdition.objects.get(pk=binding["edition_id"])
        self.assertEqual(binding["state"], "CANDIDATE")
        self.assertEqual(target.category, "تصنيف تجريبي مقترح")
        self.assertEqual(target.title, source.title)
        self.assertEqual(target.body, source.body)
        self.assertEqual(target.citations, source.citations)
        self.assertEqual(target.answer_id, source.answer_id)
        self.assertEqual(target.actions.count(), 0)
        self.assertEqual(before, self.library())
        self.assertEqual(self.inspect_binding(binding)["edition"]["state"], "CANDIDATE")
        self.assertEqual(
            EditorialBinding.objects.get().revision_id, cases._uuid(self.classification["id"])
        )

    def test_two_manual_steps_and_independent_publication_approver(self):
        binding = self.prepare()
        with self.assertRaises(cases.CaseConflict):
            self.editorial_action(binding, "APPROVE")
        self.assertEqual(self.editorial_action(binding)["state"], "REVIEWED")
        for subject in ("editor", "publisher"):
            with self.assertRaises(cases.CaseConflict):
                self.editorial_action(binding, "APPROVE", subject_id=subject)
        self.assertEqual(self.editorial_action(binding, "APPROVE")["state"], "PUBLISHED")
        self.assertEqual(self.library()[0]["id"], binding["edition_id"])
        self.assertEqual(self.library()[0]["category"], "تصنيف تجريبي مقترح")
        self.assertEqual(self.inspect_binding(binding)["edition"]["state"], "PUBLISHED")
        self.assertFalse(
            PublicationAction.objects.filter(
                edition_id=self.edition["id"], action="WITHDRAW"
            ).exists()
        )

    def test_closed_flags_policy_scope_and_confirmation(self):
        for change in (
            {"FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED": False},
            {"FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_POLICY": None},
        ):
            with override_settings(**change), self.assertRaises(cases.CaseConflict):
                self.prepare()
        for flag in (
            "FATWA_SOURCE_RIGHTS_ENABLED",
            "FATWA_SOURCE_RIGHTS_ENFORCED",
            "FATWA_RECOVERY_MAINTENANCE_REQUIRED",
        ):
            with override_settings(**{flag: False}), self.assertRaises(cases.CaseConflict):
                self.prepare()
        for value in (False, 1, "yes"):
            with self.assertRaises(cases.CaseConflict):
                self.prepare(confirmed=value)
        with (
            patch.dict(os.environ, FATWA_PRODUCTION="1"),
            self.assertRaises(MaintenanceUnavailable),
        ):
            self.prepare()
        with self.assertRaises(cases.CaseConflict):
            self.prepare(synthetic_fixtures_only=False)
        with (
            patch.object(self.simulation_policy, "permits", return_value="yes"),
            self.assertRaises(cases.CaseConflict),
        ):
            self.prepare()
        with (
            patch.object(
                self.simulation_policy, "permits", side_effect=RuntimeError("private policy detail")
            ),
            self.assertRaisesMessage(
                cases.CaseConflict, "classification_editorial_policy_unavailable"
            ),
        ):
            self.prepare()
        self.assertEqual(PublicationEdition.objects.count(), 1)
        self.assertEqual(EditorialBinding.objects.count(), 0)

    def test_pending_rejected_or_withdrawn_classifications_cannot_prepare(self):
        pending = self.proposal()
        self.simulation_policy.revision_id = pending["id"]
        with self.assertRaises(cases.CaseConflict):
            self.prepare(revision_id=pending["id"])
        self.decision(pending, "REJECT")
        with self.assertRaises(cases.CaseConflict):
            self.prepare(revision_id=pending["id"])
        self.simulation_policy.revision_id = self.classification["id"]
        self.decision(self.classification, "WITHDRAW")
        with self.assertRaises(cases.CaseConflict):
            self.prepare()

    def test_canonical_publication_actions_cannot_bypass_bound_policy(self):
        binding = self.prepare()
        with self.assertRaises(IntegrityError):
            publications.act(
                **self.common, edition_id=binding["edition_id"], action="REVIEW", reviewed=True
            )
        self.editorial_action(binding)
        with self.assertRaises(IntegrityError):
            publications.act(
                **{**self.common, "subject_id": "other"},
                edition_id=binding["edition_id"],
                action="APPROVE",
            )
        self.assertEqual(
            PublicationAction.objects.filter(edition_id=binding["edition_id"]).count(), 1
        )
        # Existing independent withdrawal remains usable even without the drill flag.
        with override_settings(FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED=False):
            publications.act(
                **{**self.common, "subject_id": "other"},
                edition_id=binding["edition_id"],
                action="WITHDRAW",
            )
        with self.assertRaises(cases.CaseConflict):
            self.inspect_binding(binding)

    def test_correction_and_knowledge_version_change_close_pending_target(self):
        binding = self.prepare()
        self.proposal(replaces_id=self.classification["id"])
        for op in (lambda: self.inspect_binding(binding), lambda: self.editorial_action(binding)):
            with self.assertRaises(cases.CaseConflict):
                op()
        self.assertEqual(
            PublicationAction.objects.filter(edition_id=binding["edition_id"]).count(), 0
        )

    def test_source_knowledge_correction_and_publication_change_are_not_inherited(self):
        binding = self.prepare()
        KnowledgeFixture.propose(self, replaces_id=self.source["id"])
        with self.assertRaises(cases.CaseConflict):
            self.editorial_action(binding)
        with self.assertRaises(cases.CaseConflict):
            self.prepare()

    def test_new_answer_evidence_blocks_prepared_candidate(self):
        binding = self.prepare()
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.add_followup(
            token=self.receipt["token"],
            text="synthetic changed facts",
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.editorial_action(binding)
        with self.assertRaises(cases.CaseConflict):
            self.inspect_binding(binding)

    def test_rights_expiry_revoke_and_late_policy_revocation_deny(self):
        binding = self.prepare()
        with patch.object(
            rights.timezone, "now", return_value=timezone.now() + timedelta(minutes=2)
        ):
            with self.assertRaises(cases.CaseConflict):
                self.inspect_binding(binding)
            with self.assertRaises(cases.CaseConflict):
                self.editorial_action(binding)
        rights.review(
            **{**self.common, "subject_id": "publisher"},
            revision_id=self.grant["id"],
            action="REVOKE",
            confirmed=True,
            note="synthetic withdrawal",
        )
        with self.assertRaises(cases.CaseConflict):
            self.editorial_action(binding)
        self.assertEqual(
            PublicationAction.objects.filter(edition_id=binding["edition_id"]).count(), 0
        )

    def test_policy_version_or_late_identity_change_rolls_back(self):
        binding = self.prepare()
        self.simulation_policy.policy_id = "changed-policy"
        with self.assertRaises(cases.CaseConflict):
            self.editorial_action(binding)
        self.simulation_policy.policy_id = SimulationPolicy.policy_id
        with patch.object(self.simulation_policy, "permits", side_effect=[True, False]):
            with self.assertRaises(cases.CaseConflict):
                self.editorial_action(binding)
        self.assertEqual(
            PublicationAction.objects.filter(edition_id=binding["edition_id"]).count(), 0
        )
        original = self.simulation_policy.permits

        def revoke(**kwargs):
            allowed = original(**kwargs)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], auth_epoch="changed"
            )
            return allowed

        with (
            patch.object(self.simulation_policy, "permits", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.inspect_binding(binding)

    def test_stale_versions_and_duplicate_concurrent_prepare(self):
        with self.assertRaises(cases.CaseConflict):
            self.prepare(expected_revision=1)
        with self.assertRaises(cases.CaseConflict):
            self.prepare(expected_evidence_version=None)
        barrier = Barrier(2)

        def prepare():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                self.prepare()
                return "created"
            except cases.CaseConflict:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(
                list(executor.map(lambda _: prepare(), range(2))), ["created", "conflict"]
            )
        self.assertEqual(EditorialBinding.objects.count(), 1)
        self.assertEqual(PublicationEdition.objects.count(), 2)

    def test_binding_append_only_and_preparation_rollback(self):
        with patch.object(self.simulation_policy, "permits", side_effect=[True, False]):
            with self.assertRaises(cases.CaseConflict):
                self.prepare()
        self.assertEqual(PublicationEdition.objects.count(), 1)
        self.assertEqual(EditorialBinding.objects.count(), 0)
        binding = self.prepare()
        for operation in (
            lambda: EditorialBinding.objects.all().update(policy_id="erase"),
            lambda: EditorialBinding.objects.all().delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        self.assertEqual(self.inspect_binding(binding)["policy_id"], SimulationPolicy.policy_id)

    def test_freeze_blocks_prepare_inspect_and_decision_without_changes(self):
        binding = self.prepare()
        # Existing maintenance API closes admissions; no isolated bypass settings.
        maintenance.enter(root=self.control, synthetic_fixtures_only=True)
        for op in (
            self.prepare,
            lambda: self.inspect_binding(binding),
            lambda: self.editorial_action(binding),
        ):
            with self.assertRaises(MaintenanceUnavailable):
                op()
        self.assertEqual(PublicationEdition.objects.count(), 2)
        self.assertEqual(
            PublicationAction.objects.filter(edition_id=binding["edition_id"]).count(), 0
        )

    def test_other_case_scope_and_foreign_publication_identifier_deny(self):
        binding = self.prepare()
        with self.assertRaises(cases.CaseConflict):
            self.inspect_binding(binding, publication_id="00000000-0000-0000-0000-000000000000")
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset()
        )
        with self.assertRaises(cases.CaseConflict):
            self.inspect_binding(binding)

    def test_competing_publication_version_and_source_withdrawal_close_binding(self):
        binding = self.prepare()
        newer = self.new_publication()
        self.assertNotEqual(newer["id"], binding["edition_id"])
        with self.assertRaises(cases.CaseConflict):
            self.editorial_action(binding)
        with self.assertRaises(cases.CaseConflict):
            self.inspect_binding(binding)
        self.assertEqual(EditorialBinding.objects.count(), 1)

    def test_concurrent_publication_approval_records_one_decision(self):
        binding = self.prepare()
        self.editorial_action(binding)
        barrier = Barrier(2)

        def approve():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                self.editorial_action(binding, "APPROVE")
                return "approved"
            except cases.CaseConflict:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(
                list(executor.map(lambda _: approve(), range(2))), ["approved", "conflict"]
            )
        self.assertEqual(
            PublicationAction.objects.filter(
                edition_id=binding["edition_id"], action="APPROVE"
            ).count(),
            1,
        )

    def test_late_rights_revocation_rolls_back_and_does_not_leak_inspection(self):
        binding = self.prepare()
        count = 0

        def revoke(**kwargs):
            nonlocal count
            count += 1
            if count == 2:
                rights.review(
                    **{**self.common, "subject_id": "publisher"},
                    revision_id=self.grant["id"],
                    action="REVOKE",
                    confirmed=True,
                    note="synthetic late source revocation",
                )
            return True

        with patch.object(self.simulation_policy, "permits", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.inspect_binding(binding)
        # The attempted inline revocation and any data result share the transaction.
        # No partial response can escape the failed final validation.
        self.assertEqual(self.inspect_binding(binding)["edition"]["state"], "CANDIDATE")

    def test_source_publication_withdrawal_blocks_bound_actions(self):
        binding = self.prepare()
        publications.act(
            **{**self.common, "subject_id": "other"},
            edition_id=self.edition["id"],
            action="WITHDRAW",
        )
        with self.assertRaises(cases.CaseConflict):
            self.editorial_action(binding)
        with self.assertRaises(cases.CaseConflict):
            self.inspect_binding(binding)
        self.assertEqual(EditorialBinding.objects.count(), 1)
