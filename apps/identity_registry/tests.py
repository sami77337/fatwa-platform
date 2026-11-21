"""Real PostgreSQL boundaries, literal origins, human verification and correction."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseSource
from apps.casework_web.access import RequestDirectory
from apps.delivery_queue.models import RequesterTrackingToken
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot
from apps.source_case_intake.models import SourceReceipt

from . import services
from .boundary import ZERO, seal
from .models import (
    IdentityMembership,
    IdentityObservation,
    LinkProposal,
    Person,
    PlatformIdentity,
    RegistryOperation,
)
from .test_support import FEATURES, Authority, RegistryFixture


@override_settings(**FEATURES)
class IdentityRegistryTests(RegistryFixture, TransactionTestCase):
    def originals(self):
        return (
            list(Case.objects.order_by("pk").values()),
            list(CaseSource.objects.order_by("pk").values()),
            list(RequesterTrackingToken.objects.order_by("pk").values()),
            [(str(row.pk), bytes(row.raw)) for row in SourceReceipt.objects.order_by("pk")],
        )

    def test_disabled_missing_authority_and_missing_pure_identity_epoch_fail_closed(self):
        with (
            override_settings(FATWA_IDENTITY_REGISTRY_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.state()
        with (
            override_settings(FATWA_IDENTITY_REGISTRY_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.state()
        with (
            patch.object(self.directory, "projection_epoch", None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.state()
        self.assertFalse(Person.objects.exists())

    def test_capture_exact_bound_platform_subject_preserves_source_bytes_and_name(self):
        before = self.originals()
        identity = self.capture()
        row = PlatformIdentity.objects.get(pk=identity["id"])
        observation = IdentityObservation.objects.get()
        source = SourceReceipt.objects.get(pk=self.receipt["receipt_id"])
        self.assertEqual(
            (row.source, row.account, row.source_subject),
            (source.source, source.account, source.sender),
        )
        self.assertEqual(observation.display_name, source.display_name)
        self.assertEqual(observation.receipt_id, source.pk)
        self.assertEqual(self.state()["identities"][0]["state"], "UNLINKED")
        self.assertEqual(before, self.originals())
        self.assertNotIn(source.original_text, observation.canonical_payload)

    def test_same_named_impostor_cannot_replace_revoked_configured_identity(self):
        self.capture()
        self.person("شخص لا يظهر للمصدر البديل")
        command = self.command()
        originals = self.originals()
        real_actor = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(real_actor, active=False)
        alternate = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        for provider in (
            alternate,
            RequestDirectory(
                alternate,
                alternate.resolve("editor"),
                authenticated_provider_id=alternate.provider_id,
            ),
        ):
            with self.assertRaisesMessage(cases.CaseConflict, "configured_directory_required"):
                services.desk(**{**self.common, "provider": provider})
            with self.assertRaisesMessage(cases.CaseConflict, "configured_directory_required"):
                services.create_person(
                    **{**command, "provider": provider},
                    label="لن يسمح بمصدر بديل",
                    reason="محاولة استخدام صلاحية قديمة مع مصدر جديد بالاسم نفسه",
                    confirmed=True,
                )
        self.assertEqual(Person.objects.count(), 1)
        self.assertEqual(self.originals(), originals)
        self.directory.identities["editor"] = real_actor
        trusted = RequestDirectory(
            self.directory, real_actor, authenticated_provider_id=self.directory.provider_id
        )
        self.assertEqual(
            services.desk(**{**self.common, "provider": trusted})["case_ref"],
            self.receipt["public_ref"],
        )

    def test_same_display_names_are_separate_unlinked_sources(self):
        one = self.capture()
        _, base = self.new_case()
        two = self.capture(base)
        self.assertNotEqual(one["id"], two["id"])
        self.assertEqual(
            set(IdentityObservation.objects.values_list("display_name", flat=True)),
            {"اسم تجريبي متكرر"},
        )
        self.assertEqual(
            [row["state"] for row in self.state()["identities"]], ["UNLINKED", "UNLINKED"]
        )
        self.assertFalse(Person.objects.exists())

    def test_native_website_session_is_explicit_and_repeated_origin_reuses_identity(self):
        _, base = self.new_case(native=True, requester="same-original-session")
        one = self.capture(base)
        _, other = self.new_case(native=True, requester="same-original-session")
        two = self.capture(other)
        self.assertEqual(one["id"], two["id"])
        self.assertEqual(PlatformIdentity.objects.get(pk=one["id"]).source, "WEBSITE_SESSION")
        self.assertEqual(IdentityObservation.objects.filter(identity_id=one["id"]).count(), 2)
        self.assertFalse(Person.objects.exists())

    def test_proposed_independent_verified_and_revoked_states_preserve_every_original(self):
        identity, person = self.capture(), self.person()
        original = self.originals()
        proposal = services.propose(
            **self.command(),
            identity_id=identity["id"],
            person_id=person["id"],
            evidence="سند بشري اصطناعي",
            confirmed=True,
        )
        self.assertEqual(self.state()["identities"][0]["state"], "POSSIBLE_MATCH")
        with self.assertRaisesMessage(cases.CaseConflict, "independent_verifier"):
            services.decide(
                **self.command(),
                identity_id=identity["id"],
                proposal_id=proposal["id"],
                kind="VERIFY",
                reason="محاولة ذاتية",
                confirmed=True,
            )
        reviewer = {**self.common, "subject_id": "other"}
        services.decide(
            **self.command(reviewer),
            identity_id=identity["id"],
            proposal_id=proposal["id"],
            kind="VERIFY",
            reason="تحقق مستقل",
            confirmed=True,
        )
        self.assertEqual(self.state()["identities"][0]["state"], "VERIFIED_LINK")
        services.decide(
            **self.command(),
            identity_id=identity["id"],
            kind="UNLINK",
            reason="سحب التحقق بسبب سند جديد",
            confirmed=True,
        )
        self.assertEqual(self.state()["identities"][0]["state"], "UNLINKED")
        self.assertEqual(
            list(
                IdentityMembership.objects.order_by("sequence").values_list("person_id", flat=True)
            ),
            [uuid.UUID(person["id"]), None],
        )
        self.assertEqual(self.originals(), original)

    def test_distinct_link_and_verify_permissions_and_rejected_proposal(self):
        identity, person = self.capture(), self.person()
        self.authority.denied.add("LINK")
        with self.assertRaises(cases.CaseConflict):
            services.propose(
                **self.command(),
                identity_id=identity["id"],
                person_id=person["id"],
                evidence="سند",
                confirmed=True,
            )
        self.assertFalse(LinkProposal.objects.exists())
        self.authority.denied.clear()
        proposal = services.propose(
            **self.command(),
            identity_id=identity["id"],
            person_id=person["id"],
            evidence="سند",
            confirmed=True,
        )
        reviewer = {**self.common, "subject_id": "other"}
        self.authority.denied.add("VERIFY")
        with self.assertRaises(cases.CaseConflict):
            services.decide(
                **self.command(reviewer),
                identity_id=identity["id"],
                proposal_id=proposal["id"],
                kind="VERIFY",
                reason="تحقق",
                confirmed=True,
            )
        self.authority.denied.clear()
        services.decide(
            **self.command(reviewer),
            identity_id=identity["id"],
            proposal_id=proposal["id"],
            kind="REJECT",
            reason="السند غير كافٍ",
            confirmed=True,
        )
        self.assertEqual(self.state()["identities"][0]["state"], "UNLINKED")
        self.assertFalse(IdentityMembership.objects.exists())

    def test_merge_and_split_preview_versions_and_complete_audit_no_case_merge(self):
        one, person_a = self.capture(), self.person("الشخص الأول")
        self.link(one, person_a)
        _, second = self.new_case()
        two, person_b = self.capture(second), self.person("الشخص الثاني")
        self.link(two, person_b, second)
        before = self.originals()
        preview = services.prepare(
            **self.common,
            kind="MERGE",
            source_person_id=person_b["id"],
            target_person_id=person_a["id"],
        )
        self.assertEqual(len(preview["affected_cases"]), 2)
        self.assertEqual(IdentityMembership.objects.count(), 2)
        command = self.command()
        services.apply(
            **command,
            preview=preview,
            reason="تأكدت علاقة الشخصين في بيانات الاختبار",
            confirmed=True,
        )
        self.assertEqual({row["person_id"] for row in self.state()["identities"]}, {person_a["id"]})
        with self.assertRaises(cases.CaseConflict):
            services.apply(**command, preview=preview, reason="إعادة تشغيل", confirmed=True)
        split = services.prepare(
            **self.common,
            kind="SPLIT",
            source_person_id=person_a["id"],
            target_person_id=person_b["id"],
            identity_ids=[two["id"]],
        )
        services.apply(
            **self.command(), preview=split, reason="تصحيح فصل رابط واحد", confirmed=True
        )
        self.assertEqual(IdentityMembership.objects.filter(identity_id=two["id"]).count(), 3)
        self.assertEqual(
            [item["kind"] for item in self.state()["history"]],
            ["VERIFY", "VERIFY", "MERGE", "SPLIT"],
        )
        self.assertEqual(before, self.originals())

    def test_merge_and_split_have_independent_capabilities_and_require_exact_selection(self):
        one, person_a = self.capture(), self.person("أ")
        self.link(one, person_a)
        person_b = self.person("ب")
        self.authority.denied.add("MERGE")
        with self.assertRaises(cases.CaseConflict):
            services.prepare(
                **self.common,
                kind="MERGE",
                source_person_id=person_a["id"],
                target_person_id=person_b["id"],
            )
        self.authority.denied.clear()
        with self.assertRaisesMessage(cases.CaseConflict, "split_subset"):
            services.prepare(
                **self.common,
                kind="SPLIT",
                source_person_id=person_a["id"],
                target_person_id=person_b["id"],
                identity_ids=[one["id"]],
            )
        preview = services.prepare(
            **self.common,
            kind="MERGE",
            source_person_id=person_a["id"],
            target_person_id=person_b["id"],
        )
        self.person("حدث لاحق")
        with self.assertRaises(cases.CaseConflict):
            services.apply(**self.command(), preview=preview, reason="معاينة قديمة", confirmed=True)
        self.assertEqual(IdentityMembership.objects.count(), 1)

    def test_scoped_search_and_group_operation_never_expose_hidden_case_or_person(self):
        one, person_a = self.capture(), self.person("مسموح")
        self.link(one, person_a)
        receipt, base = self.new_case()
        two, person_b = self.capture(base), self.person("سر مخفي", base)
        self.link(two, person_b, base)
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset({self.receipt["public_ref"]})
        )
        data = self.state()
        self.assertEqual(len(data["identities"]), 1)
        self.assertNotIn("سر مخفي", str(data))
        self.assertNotIn(receipt["public_ref"], str(data))
        with self.assertRaises(cases.CaseConflict):
            services.prepare(
                **self.common,
                kind="MERGE",
                source_person_id=person_b["id"],
                target_person_id=person_a["id"],
            )

    def test_current_scope_revocation_and_equal_authority_replacement_after_read_deny_whole(self):
        self.capture()
        original = services.desk_locked

        def revoke(guard, **kwargs):
            result = original(guard, **kwargs)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], active=False
            )
            return result

        with (
            patch.object(services, "desk_locked", side_effect=revoke),
            self.assertRaises(Exception),
        ):
            self.state()
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], active=True
        )

        class ValueEqual(Authority):
            def __eq__(self, other):
                return True

        replacement = ValueEqual(self.authority.refs)

        def replace_policy(guard, **kwargs):
            result = original(guard, **kwargs)
            from django.conf import settings

            settings.FATWA_IDENTITY_REGISTRY_AUTHORITY = replacement
            return result

        with (
            patch.object(services, "desk_locked", side_effect=replace_policy),
            self.assertRaises(cases.CaseConflict),
        ):
            self.state()

    def test_late_permission_callback_change_rolls_back_intentional_write(self):
        command = self.command()
        original = services.seal

        def revoke_after_insert(row):
            result = original(row)
            if isinstance(row, Person):
                self.authority.denied.add("CREATE_PERSON")
            return result

        with (
            patch.object(services, "seal", side_effect=revoke_after_insert),
            self.assertRaises(cases.CaseConflict),
        ):
            services.create_person(**command, label="لن يبقى", reason="اختبار", confirmed=True)
        self.assertFalse(Person.objects.exists())

    def test_sql_mutation_and_forged_self_verification_are_rejected(self):
        identity, person = self.capture(), self.person()
        proposal = services.propose(
            **self.command(),
            identity_id=identity["id"],
            person_id=person["id"],
            evidence="سند",
            confirmed=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Person.objects.update(label="تغيير بلا تاريخ")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlatformIdentity.objects.all().delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            seal(
                RegistryOperation(
                    case_id=self.common["case_id"],
                    kind="VERIFY",
                    proposal_id=proposal["id"],
                    target_person_id=person["id"],
                    changes=[
                        {
                            "identity_id": identity["id"],
                            "before_digest": ZERO,
                            "before_person": None,
                            "after_person": person["id"],
                            "sequence": 1,
                        }
                    ],
                    reason="تحقق ذاتي مزور",
                    preview_digest=ZERO,
                    request_key=uuid.uuid4(),
                    provider_id=self.directory.provider_id,
                    subject_id="editor",
                    auth_epoch="epoch-1",
                )
            )
        self.assertFalse(RegistryOperation.objects.exists())

    def test_sql_incomplete_operation_is_rejected_at_commit(self):
        identity, person = self.capture(), self.person()
        proposal = services.propose(
            **self.command(),
            identity_id=identity["id"],
            person_id=person["id"],
            evidence="سند",
            confirmed=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            seal(
                RegistryOperation(
                    case_id=self.common["case_id"],
                    kind="VERIFY",
                    proposal_id=proposal["id"],
                    target_person_id=person["id"],
                    changes=[
                        {
                            "identity_id": identity["id"],
                            "before_digest": ZERO,
                            "before_person": None,
                            "after_person": person["id"],
                            "sequence": 1,
                        }
                    ],
                    reason="لم تكتمل الروابط",
                    preview_digest=ZERO,
                    request_key=uuid.uuid4(),
                    provider_id=self.directory.provider_id,
                    subject_id="other",
                    auth_epoch="epoch-1",
                )
            )
        self.assertFalse(RegistryOperation.objects.exists())

    def test_concurrent_optimistic_commands_allow_only_one_current_write(self):
        command = self.command()

        def create(label):
            connections.close_all()
            try:
                try:
                    services.create_person(
                        **{**command, "request_key": uuid.uuid4()},
                        label=label,
                        reason="تنافس اصطناعي",
                        confirmed=True,
                    )
                    return "saved"
                except cases.CaseConflict:
                    return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, ["أ", "ب"]))
        self.assertEqual(sorted(outcomes), ["saved", "stale"])
        self.assertEqual(Person.objects.count(), 1)

    def test_no_person_link_changes_case_source_hash_token_or_delivery_origin(self):
        identity, person = self.capture(), self.person()
        before = self.originals()
        case = Case.objects.get(pk=self.receipt["case_id"])
        origin = cases._delivery_origin_for_locked_case(case)
        self.link(identity, person)
        after = Case.objects.get(pk=case.pk)
        self.assertEqual(cases._delivery_origin_for_locked_case(after), origin)
        self.assertEqual(before, self.originals())
        self.assertEqual(after.requester_id, case.requester_id)
        self.assertNotEqual(after.requester_id, person["id"])

    def test_pending_proposal_requires_its_distinct_owner_case_scope_and_read(self):
        identity = self.capture()
        _, person_base = self.new_case()
        person = self.person("شخص القضية الثانية", person_base)
        receipt, proposal_base = self.new_case(native=True)
        self.authority.denied.add(("LINK", receipt["public_ref"]))
        with self.assertRaises(cases.CaseConflict):
            services.propose(
                **self.command(proposal_base),
                identity_id=identity["id"],
                person_id=person["id"],
                evidence="سند خاص بالقضية الثالثة",
                confirmed=True,
            )
        self.assertFalse(LinkProposal.objects.exists())
        self.authority.denied.clear()
        services.propose(
            **self.command(proposal_base),
            identity_id=identity["id"],
            person_id=person["id"],
            evidence="سند خاص بالقضية الثالثة",
            confirmed=True,
        )
        self.assertIn("سند خاص بالقضية الثالثة", str(self.state()))
        original = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(
            original, case_keys=original.case_keys - {receipt["public_ref"]}
        )
        projected = self.state()
        self.assertNotIn("سند خاص بالقضية الثالثة", str(projected))
        self.assertNotIn(identity["id"], [row["id"] for row in projected["identities"]])
        self.directory.identities["editor"] = original
        self.authority.denied.add(("READ", receipt["public_ref"]))
        with self.assertRaises(cases.CaseConflict):
            self.state()
