import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.operational_workspace import notes

from . import catalog, services, store
from .models import PermissionRevision
from .test_support import FEATURES, Fixture


@override_settings(**FEATURES)
class PermissionTests(Fixture, TransactionTestCase):
    def test_sql_nulls_cannot_bypass_closed_rules_or_audit_context(self):
        self.seeded()
        original = PermissionRevision.objects.get(kind="SET")
        for path in (
            ("definition", "rules", 0, "effect"),
            ("definition", "rules", 0, "scope", "domain"),
            ("definition", "rules", 0, "scope", "case_ref"),
            ("definition", "rules", 0, "scope", "action"),
            ("definition", "rules", 0, "scope", "resource", "kind"),
            ("definition", "rules", 0, "scope", "resource", "section"),
            ("context", "ledger"),
        ):
            row = copy.deepcopy(original)
            row.pk, row.number, row.previous_digest = uuid.uuid4(), 2, original.digest
            row.change, row.request_key = "REPLACE", uuid.uuid4()
            value = getattr(row, path[0])
            for key in path[1:-1]:
                value = value[key]
            value[path[-1]] = None
            with self.subTest(path=path), self.assertRaises(IntegrityError), transaction.atomic():
                store.seal(row).save(force_insert=True)
        row = copy.deepcopy(original)
        row.pk, row.number, row.previous_digest = uuid.uuid4(), 2, original.digest
        row.change, row.request_key = "REPLACE", uuid.uuid4()
        row.context.pop("ledger")
        with self.assertRaises(IntegrityError), transaction.atomic():
            store.seal(row).save(force_insert=True)
        for changes in ({"label": None}, {"label": 7}, {"rank": 101}):
            row = copy.deepcopy(original)
            row.pk, row.number, row.previous_digest = uuid.uuid4(), 2, original.digest
            row.change, row.request_key = "REPLACE", uuid.uuid4()
            row.definition["rules"] = [
                {
                    "effect": "ALLOW",
                    "scope": {
                        "domain": catalog.DOMAIN,
                        "case_ref": self.receipt["public_ref"],
                        "action": "SET_PRIORITY",
                        "resource": {
                            "kind": "CASE_COORDINATION",
                            "case_id": self.receipt["case_id"],
                            "priority": "normal",
                            "label": "عادية",
                            "rank": 50,
                            "policy_sha256": "f" * 64,
                            **changes,
                        },
                    },
                }
            ]
            with (
                self.subTest(changes=changes),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                store.seal(row).save(force_insert=True)
        self.assertEqual(PermissionRevision.objects.count(), 2)
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))

    def test_removing_a_deny_requires_its_exact_rule_mandate_and_candidates_never_grant(self):
        self.seeded()
        self.save(
            kind="USER",
            definition={
                "sets": [self.template_key],
                "overrides": [self.rule("ADD_INTERNAL_NOTE", "DENY")],
            },
        )
        before = store.fingerprint()
        denied_rule = catalog.digest(self.rule("ADD_INTERNAL_NOTE", "DENY"))
        saved_grants = set(self.authority.grants)
        self.authority.grants = {
            value
            for value in self.authority.grants
            if not (
                value[0] == "admin"
                and value[1] == "MANAGE_RULE"
                and value[4] == "operator"
                and value[6] == denied_rule
            )
        }
        with self.assertRaises(cases.CaseConflict):
            self.save(kind="USER", definition={"sets": [self.template_key], "overrides": []})
        self.assertEqual(store.fingerprint(), before)
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        self.authority.grants = saved_grants
        self.authority.revoke("WRITE_USER", target="operator")
        with self.assertRaises(cases.CaseConflict):
            self.save(kind="USER", definition={"sets": [], "overrides": []})
        self.assertEqual(store.fingerprint(), before)

    def test_exact_resource_and_reserved_shape_reject_overbroad_rules(self):
        self.save()
        for alteration in (
            {"case_ref": "outside-case"},
            {"resource": {**self.scopes["READ_CASE"]["resource"], "case_id": str(uuid.uuid4())}},
            {"resource": {**self.scopes["READ_CASE"]["resource"], "section": "*"}},
            {"resource": {**self.scopes["READ_CASE"]["resource"], "subject": "all"}},
        ):
            rule = {"scope": {**self.scopes["READ_CASE"], **alteration}, "effect": "ALLOW"}
            with self.assertRaises(cases.CaseConflict):
                self.save(kind="USER", definition={"sets": [], "overrides": [rule]})
        self.assertEqual(PermissionRevision.objects.count(), 1)

    def test_populated_migration_reversal_restores_exact_audit_guards(self):
        self.seeded()
        before = store.fingerprint()
        executor = MigrationExecutor(connection)
        executor.migrate([("permission_sets", "0001_initial")])
        executor = MigrationExecutor(connection)
        executor.migrate([("permission_sets", "0002_integrity")])
        self.assertEqual(store.fingerprint(), before)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PermissionRevision.objects.update(note="تغيير بعد الرجوع")
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))

    def test_saved_template_and_user_binding_authorize_real_organizer_note(self):
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        template, user = self.seeded()
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        result = self.note()
        self.assertEqual(result["role"], "ORGANIZER")
        self.assertIn("منظم مخول", result["history"][0]["note"])
        self.assertEqual(PermissionRevision.objects.count(), 2)
        self.assertEqual(
            PermissionRevision.objects.get(pk=user["id"]).definition["sets"], [template["key"]]
        )
        self.assert_original()

    def test_individual_deny_defeats_template_allow_and_other_allow(self):
        self.seeded()
        self.save(
            kind="USER",
            definition={
                "sets": [self.template_key],
                "overrides": [self.rule("ADD_INTERNAL_NOTE", "DENY")],
            },
        )
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        self.assertTrue(self.allowed("READ_INTERNAL_NOTES"))
        with self.assertRaises(cases.CaseConflict):
            self.note()
        other = str(uuid.uuid4())
        self.authority.allow_set(other)
        self.save(
            key=other,
            definition={"title": "رفض مستقل", "rules": [self.rule("ADD_INTERNAL_NOTE", "DENY")]},
        )
        self.save(
            kind="USER",
            definition={
                "sets": [self.template_key, other],
                "overrides": [self.rule("ADD_INTERNAL_NOTE")],
            },
        )
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        self.save(kind="USER", definition={"sets": [self.template_key], "overrides": []})
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        self.note("قراءة وكتابة إيجابية بعد إزالة الرفض المخولة")
        self.assert_original()

    def test_template_revision_previews_every_affected_user_and_needs_their_mandate(self):
        self.seeded()
        proposal = self.proposal(
            definition={
                "title": "قراءة فقط",
                "rules": [self.rule("READ_CASE"), self.rule("READ_INTERNAL_NOTES")],
            }
        )
        plan = self.prepare(proposal)
        self.assertEqual([row["subject"] for row in plan["summaries"]], ["operator"])
        self.assertTrue(
            any(
                row["label"] == catalog.LABELS["ADD_INTERNAL_NOTE"]
                for row in plan["summaries"][0]["changes"]
            )
        )
        self.authority.revoke("WRITE_USER", target="operator")
        with self.assertRaises(cases.CaseConflict):
            with services.apply(plan=plan, confirmed=True, **self.base):
                pass
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        self.assertEqual(PermissionRevision.objects.count(), 2)

    def test_disable_and_fresh_revert_append_history_and_restore_current_use(self):
        template, user = self.seeded()
        self.save(change="DISABLE")
        self.assertFalse(self.allowed("READ_CASE"))
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        restored = self.save(change="REVERT", reverted_from=template["id"])
        self.assertEqual(restored["number"], 3)
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        self.save(kind="USER", change="DISABLE")
        self.assertFalse(self.allowed("READ_CASE"))
        self.save(kind="USER", change="REVERT", reverted_from=user["id"])
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        self.note()
        self.assertEqual(PermissionRevision.objects.count(), 6)
        self.assert_original()

    def test_no_self_grant_or_edit_of_template_bound_to_admin(self):
        self.save()
        with self.assertRaises(cases.CaseConflict):
            self.save(kind="USER", key="admin")
        self.save(kind="USER", key="admin", base={**self.base, "subject_id": "mufti"})
        with self.assertRaises(cases.CaseConflict):
            self.save(
                definition={"title": "زيادة ذاتية", "rules": [self.rule("ADD_INTERNAL_NOTE")]}
            )
        self.save(
            kind="USER", key="admin", change="DISABLE", base={**self.base, "subject_id": "mufti"}
        )
        with self.assertRaises(cases.CaseConflict):
            self.save(change="DISABLE")
        self.assertEqual(PermissionRevision.objects.count(), 3)

    def test_roles_alone_never_grant_administration_or_scientific_authority(self):
        for subject in ("operator", "mufti"):
            if subject == "mufti":
                self.authority.revoke("ENTER", actor=subject)
            with self.assertRaises(cases.CaseConflict):
                self.save(base={**self.base, "subject_id": subject})
        self.seeded()
        for action in (
            "APPROVE_TRANSCRIPT_MEANING",
            "APPROVE_ANSWER",
            "CREATE_MUFTI",
            "MANAGE_PERMISSIONS",
            "*",
        ):
            invalid = self.rule("ADD_INTERNAL_NOTE")
            invalid["scope"] = {**invalid["scope"], "action": action}
            with self.assertRaises(cases.CaseConflict):
                self.save(kind="USER", definition={"sets": [], "overrides": [invalid]})
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                **self.operator,
                case_id=self.receipt["case_id"],
                text="غير مخول",
                expected_revision=1,
                expected_evidence_version=1,
            )
        self.assert_original()

    def test_stale_preview_target_epoch_scope_or_policy_never_writes(self):
        self.seeded()
        plan = self.prepare(kind="USER", definition={"sets": [], "overrides": []})
        before = store.fingerprint()
        original = self.directory.identities["operator"]
        for actor in (
            replace(original, auth_epoch="epoch-2"),
            replace(original, case_keys=frozenset({"different-case"})),
            replace(original, active=False),
        ):
            self.directory.identities["operator"] = actor
            with self.assertRaises(cases.CaseConflict):
                with services.apply(plan=plan, confirmed=True, **self.base):
                    pass
            self.assertEqual(store.fingerprint(), before)
        self.directory.identities["operator"] = original
        try:
            with self.assertRaises(cases.CaseConflict):
                with services.apply(plan=plan, confirmed=True, **self.base):
                    settings.FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY = copy.copy(self.authority)
        finally:
            settings.FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY = self.authority
        self.assertEqual(store.fingerprint(), before)

    def test_final_revocation_rolls_back_append_and_discards_prior_operational_read(self):
        self.seeded()
        plan = self.prepare(kind="USER", definition={"sets": [], "overrides": []})
        before = store.fingerprint()
        grants = set(self.authority.grants)
        with self.assertRaises(cases.CaseConflict):
            with services.apply(plan=plan, confirmed=True, **self.base):
                self.authority.revoke("WRITE_USER", target="operator")
        self.assertEqual(store.fingerprint(), before)
        self.authority.grants = grants
        with self.assertRaises(cases.CaseConflict):
            with notes.projection(case_ref=self.receipt["public_ref"], **self.operator):
                self.save(kind="USER", change="DISABLE")
        self.assertEqual(store.fingerprint(), before)
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))
        self.note()

    def test_last_callback_cannot_hide_unrelated_append_in_expected_watermark(self):
        self.seeded()
        before = store.fingerprint()
        fired = False

        def mutate(values):
            nonlocal fired
            if not fired and values["operation"] == "WRITE_USER":
                fired = True
                self.authority.hook = None
                self.save(change="DISABLE")

        self.authority.hook = mutate
        with self.assertRaises(cases.CaseConflict):
            self.save(kind="USER", definition={"sets": [], "overrides": []})
        self.assertTrue(fired)
        self.assertEqual(store.fingerprint(), before)

    def test_expiry_target_identity_and_feature_revoke_stored_use(self):
        self.seeded()
        actor = self.directory.identities["operator"]
        self.directory.identities["operator"] = replace(actor, auth_epoch="epoch-2")
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        self.directory.identities["operator"] = actor
        with override_settings(FATWA_PERMISSION_SETS_ENABLED=False):
            self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        with patch(
            "apps.permission_sets.store.timezone.now",
            return_value=timezone.now() + timedelta(minutes=31),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.allowed("ADD_INTERNAL_NOTE")
        self.assertTrue(self.allowed("ADD_INTERNAL_NOTE"))

    def test_sql_guards_reject_mutation_resealed_scientific_rule_and_self_user(self):
        self.seeded()
        row = PermissionRevision.objects.filter(kind="SET").first()
        for operation in (
            lambda: PermissionRevision.objects.filter(pk=row.pk).update(note="تغيير"),
            lambda: PermissionRevision.objects.filter(pk=row.pk).delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        for forbidden in ("APPROVE_TRANSCRIPT_MEANING", "MANAGE_PERMISSIONS"):
            forged = copy.deepcopy(row)
            forged.pk, forged.number, forged.previous_digest = uuid.uuid4(), 2, row.digest
            forged.change, forged.request_key = "REPLACE", uuid.uuid4()
            forged.definition["rules"][0]["scope"]["action"] = forbidden
            with self.assertRaises(IntegrityError), transaction.atomic():
                store.seal(forged).save(force_insert=True)
        user = PermissionRevision.objects.filter(kind="USER").first()
        user.pk, user.number, user.previous_digest = uuid.uuid4(), 2, user.digest
        user.change, user.request_key, user.actor_subject_id = "REPLACE", uuid.uuid4(), "operator"
        with self.assertRaises(IntegrityError), transaction.atomic():
            store.seal(user).save(force_insert=True)
        self.assertEqual(PermissionRevision.objects.count(), 2)

    def test_two_confirmations_of_one_preview_have_one_winner(self):
        self.seeded()
        plan = self.prepare(kind="USER", definition={"sets": [], "overrides": []})

        def submit():
            close_old_connections()
            try:
                with services.apply(plan=plan, confirmed=True, **self.base):
                    return "saved"
            except cases.CaseConflict:
                return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: submit(), range(2)))
        self.assertCountEqual(values, ["saved", "stale"])
        self.assertEqual(PermissionRevision.objects.count(), 3)
        self.assertFalse(self.allowed("ADD_INTERNAL_NOTE"))
        self.assert_original()
