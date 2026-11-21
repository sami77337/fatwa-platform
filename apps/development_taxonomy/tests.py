"""Real SQL versions, exact human mappings, canonical bindings and safe rollback."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseSource
from apps.casework_web.access import RequestDirectory
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot

from . import services
from .boundary import seal
from .models import (
    CaseClassification,
    Concept,
    MigrationExecution,
    MigrationPlan,
    TreeVersion,
)
from .test_support import FEATURES, TaxonomyFixture, initial_nodes


@override_settings(**FEATURES)
class DevelopmentTaxonomyTests(TaxonomyFixture, TransactionTestCase):
    def originals(self):
        return [
            list(model.objects.order_by("pk").values())
            for model in (Case, CaseSource, AnswerRevision, CaseDecision)
        ]

    def execute(self, plan, kind="APPLY"):
        return services.execute(
            **self.command(),
            plan_id=plan["id"],
            kind=kind,
            reason="إجراء بشري محدد بعد المعاينة",
            confirmed=True,
        )

    def test_disabled_missing_authority_and_directory_epoch_fail_closed(self):
        with (
            override_settings(FATWA_DEVELOPMENT_TAXONOMY_ENABLED=False),
            self.assertRaises(cases.CaseConflict),
        ):
            self.state()
        with (
            override_settings(FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.state()
        with (
            patch.object(self.directory, "projection_epoch", None),
            self.assertRaises(cases.CaseConflict),
        ):
            self.state()
        self.assertFalse(TreeVersion.objects.exists())

    def test_multilevel_stable_ids_rename_move_and_immutable_meaning(self):
        source = self.review(self.save())
        first = self.state(version=source["id"])["selected"]
        self.assertEqual([node["depth"] for node in first["nodes"]], [1, 2, 3, 2])
        target, _ = self.renamed(source)
        second = self.state(version=target["id"])["selected"]
        self.assertEqual(
            [node["id"] for node in first["nodes"]], [node["id"] for node in second["nodes"]]
        )
        self.assertEqual(second["nodes"][2]["parent"], first["nodes"][3]["id"])
        self.assertNotEqual(first["nodes"][1]["name"], second["nodes"][1]["name"])
        changed = self.nodes(target)
        changed[1]["definition"] = "معنى مختلف ممنوع على المعرف نفسه"
        with self.assertRaisesMessage(cases.CaseConflict, "stable_meaning"):
            self.save(changed, tree=target)
        self.assertEqual(Concept.objects.count(), 4)
        self.assertEqual(TreeVersion.objects.count(), 2)

    def test_same_named_unconfigured_identity_provider_is_not_trusted(self):
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
        trusted = RequestDirectory(
            self.directory,
            self.directory.resolve("editor"),
            authenticated_provider_id=self.directory.provider_id,
        )
        self.assertEqual(
            services.desk(**{**self.common, "provider": trusted})["case_ref"],
            self.receipt["public_ref"],
        )

    def test_independent_human_tree_review_required_before_real_binding(self):
        source = self.save()
        with self.assertRaises(cases.CaseConflict):
            self.bind(source)
        with self.assertRaisesMessage(cases.CaseConflict, "independent_review"):
            services.review(
                **self.command(),
                target_kind="VERSION",
                target_id=source["id"],
                action="APPROVE",
                reason="تحقق ذاتي",
                confirmed=True,
            )
        self.review(source)
        self.bind(source)
        state = self.state()["binding"]
        self.assertEqual(state["primary"], "باب اصطناعي ألف")
        self.assertEqual(state["additional"], ["باب اصطناعي باء"])
        self.assertTrue(state["current_answer"])

    def test_primary_additional_remain_pinned_until_explicit_migration(self):
        source = self.review(self.save())
        self.bind(source)
        before = self.originals()
        target, mapping = self.renamed(source)
        self.assertEqual(self.state()["binding"]["primary"], "باب اصطناعي ألف")
        self.assertEqual(self.state()["binding"]["version_id"], source["id"])
        plan = self.plan(source, target, mapping)
        self.assertEqual(CaseClassification.objects.count(), 1)
        with self.assertRaisesMessage(cases.CaseConflict, "reviewed_mapping"):
            self.execute(plan)
        self.review(plan, "PLAN")
        self.execute(plan)
        self.assertEqual(self.state()["binding"]["primary"], "باب ألف بعد إعادة تسمية")
        self.assertEqual(self.state()["history"][0]["primary"], "باب اصطناعي ألف")
        self.execute(plan, "ROLLBACK")
        self.assertEqual(self.state()["binding"]["version_id"], source["id"])
        self.assertEqual(CaseClassification.objects.count(), 3)
        self.assertEqual(before, self.originals())

    def test_actual_two_case_migration_and_rollback_are_atomic_and_audited(self):
        source = self.review(self.save())
        self.bind(source)
        _, base = self.new_case()
        self.bind(source, base)
        target, mapping = self.renamed(source)
        preview = services.preview(
            **self.common,
            source_version_id=source["id"],
            target_version_id=target["id"],
            mapping=mapping,
        )
        self.assertEqual(len(preview["impacts"]), 2)
        plan = self.review(self.plan(source, target, mapping), "PLAN")
        self.assertEqual(self.execute(plan)["changed"], 2)
        self.assertEqual(self.state(base)["binding"]["version_id"], target["id"])
        self.assertEqual(self.execute(plan, "ROLLBACK")["changed"], 2)
        self.assertEqual(self.state(base)["binding"]["version_id"], source["id"])
        self.assertEqual(MigrationExecution.objects.count(), 2)
        self.assertEqual(CaseClassification.objects.count(), 6)

    def test_cycle_unknown_parent_and_duplicate_primary_additional_denied(self):
        bad = initial_nodes()
        bad[0]["parent"] = "new:2"
        with self.assertRaisesMessage(cases.CaseConflict, "cycle_or_depth"):
            self.save(bad)
        source = self.review(self.save())
        with self.assertRaises(cases.CaseConflict):
            self.bind(source, primary_index=1, additional_indices=(1,))
        self.assertFalse(CaseClassification.objects.exists())

    def test_split_requires_exact_human_choice_and_new_concept_ids(self):
        source = self.review(self.save())
        self.bind(source, additional_indices=())
        original = self.nodes(source)
        nodes = [
            original[0],
            original[3],
            {
                "key": "new:0",
                "parent": original[0]["key"],
                "name": "جزء ألف اصطناعي",
                "definition": "معنى تجريبي جزئي جديد ألف",
            },
            {
                "key": "new:1",
                "parent": original[0]["key"],
                "name": "جزء باء اصطناعي",
                "definition": "معنى تجريبي جزئي جديد باء",
            },
        ]
        target = self.review(self.save(nodes, tree=source))
        target_nodes = TreeVersion.objects.get(pk=target["id"]).nodes
        split_ids = [target_nodes[2]["id"], target_nodes[3]["id"]]
        mapping = [
            {
                "source": row["key"],
                "kind": "SPLIT"
                if i == 1
                else "NO_EQUIVALENT"
                if i == 2
                else "MOVED"
                if i == 3
                else "SAME",
                "targets": split_ids if i == 1 else [] if i == 2 else [row["key"]],
                "reason": "تحديد إنساني للمعنى والنسخة",
            }
            for i, row in enumerate(original)
        ]
        with self.assertRaises(cases.CaseConflict):
            self.plan(source, target, mapping, resolutions=[])
        resolution = [
            {
                "case_id": self.receipt["case_id"],
                "hold": False,
                "primary": split_ids[0],
                "additional": [split_ids[1]],
                "reason": "اخترت صراحة كلا الجزأين لهذه المسألة",
            }
        ]
        plan = self.review(self.plan(source, target, mapping, resolution), "PLAN")
        self.execute(plan)
        self.assertEqual(self.state()["binding"]["primary_id"], split_ids[0])
        self.assertEqual(self.state()["binding"]["additional_ids"], [split_ids[1]])

    def test_mapping_edge_budget_is_enforced_by_services_and_database(self):
        nodes = [
            {
                "key": f"new:{index}",
                "parent": "",
                "name": f"معنى مصدر اصطناعي {index}",
                "definition": f"تعريف مصدر اصطناعي مستقل {index}",
            }
            for index in range(17)
        ]
        source = self.review(self.save(nodes))
        targets = [
            {**row, "name": f"معنى جديد {index}", "definition": f"تعريف جديد {index}"}
            for index, row in enumerate(nodes[:16])
        ]
        target = self.review(self.save(targets, tree=source))
        source_row = TreeVersion.objects.get(pk=source["id"])
        target_row = TreeVersion.objects.get(pk=target["id"])
        mapping = [
            {
                "source": row["id"],
                "kind": "SPLIT",
                "targets": [node["id"] for node in target_row.nodes],
                "reason": "علاقة بشرية اصطناعية لاختبار الحد الإجمالي",
            }
            for row in source_row.nodes
        ]
        self.assertEqual(sum(len(row["targets"]) for row in mapping), 272)
        with self.assertRaisesMessage(cases.CaseConflict, "mapping_edge_bound"):
            services.preview(
                **self.common,
                source_version_id=source["id"],
                target_version_id=target["id"],
                mapping=mapping,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            seal(
                MigrationPlan(
                    tree=source_row.tree,
                    source_version=source_row,
                    target_version=target_row,
                    mapping=mapping,
                    manifest=[],
                    reason="لا يجوز تجاوز الحد عبر كتابة مباشرة",
                    request_key=uuid.uuid4(),
                    provider_id=self.directory.provider_id,
                    subject_id="editor",
                    auth_epoch="epoch-1",
                )
            )
        self.assertFalse(MigrationPlan.objects.exists())

    def test_missing_equivalent_retains_old_binding_and_never_guesses_or_drops(self):
        source = self.review(self.save())
        self.bind(source, additional_indices=())
        second, second_base = self.new_case()
        self.bind(source, second_base, primary_index=3, additional_indices=())
        original = self.nodes(source)
        target = self.review(self.save([original[0], original[3]], tree=source))
        mapping = [
            {
                "source": row["key"],
                "kind": "NO_EQUIVALENT" if i in {1, 2} else "MOVED" if i == 3 else "SAME",
                "targets": [] if i in {1, 2} else [row["key"]],
                "reason": "لا مقابل للمعنى في النسخة الجديدة",
            }
            for i, row in enumerate(original)
        ]
        resolution = [
            {
                "case_id": self.receipt["case_id"],
                "hold": False,
                "primary": original[3]["key"],
                "additional": [],
                "reason": "محاولة فرض بديل",
            }
        ]
        resolution.append(
            {
                "case_id": second["case_id"],
                "hold": False,
                "primary": original[3]["key"],
                "additional": [],
                "reason": "نقل التصنيف الآخر ذي المقابل الواضح",
            }
        )
        with self.assertRaisesMessage(cases.CaseConflict, "requires_hold"):
            self.plan(source, target, mapping, resolution)
        resolution[0].update(
            hold=True, primary="", reason="أبقي الرابط القديم إلى مراجعة بشرية لاحقة"
        )
        plan = self.review(self.plan(source, target, mapping, resolution), "PLAN")
        result = self.execute(plan)
        self.assertEqual((result["changed"], result["held"]), (1, 1))
        self.assertEqual(self.state()["binding"]["version_id"], source["id"])
        self.assertEqual(self.state(second_base)["binding"]["version_id"], target["id"])
        self.assertEqual(CaseClassification.objects.count(), 3)
        self.execute(plan, "ROLLBACK")
        self.assertEqual(self.state(second_base)["binding"]["version_id"], source["id"])

    def test_merge_replaces_two_meanings_with_new_reviewed_identity(self):
        source = self.review(self.save())
        self.bind(source)
        original = self.nodes(source)
        nodes = [
            original[0],
            {
                "key": "new:0",
                "parent": original[0]["key"],
                "name": "مفهوم مركب اصطناعي",
                "definition": "معنى تجريبي مركب جديد؛ لا يعيد استخدام أي معرف",
            },
        ]
        target = self.review(self.save(nodes, tree=source))
        merged = TreeVersion.objects.get(pk=target["id"]).nodes[1]["id"]
        mapping = [
            {
                "source": row["key"],
                "kind": "MERGED" if i in {1, 3} else "NO_EQUIVALENT" if i == 2 else "SAME",
                "targets": [merged] if i in {1, 3} else [] if i == 2 else [row["key"]],
                "reason": "دمج موثق للمعنيين دون إعادة استخدام هوية",
            }
            for i, row in enumerate(original)
        ]
        plan = self.review(
            self.plan(
                source,
                target,
                mapping,
                [
                    {
                        "case_id": self.receipt["case_id"],
                        "hold": False,
                        "primary": merged,
                        "additional": [],
                        "reason": "يشمل المفهوم المركب التصنيفين القديمين",
                    }
                ],
            ),
            "PLAN",
        )
        self.execute(plan)
        self.assertEqual(self.state()["binding"]["primary_id"], merged)
        self.assertEqual(Concept.objects.count(), 5)

    def test_hidden_case_prevents_global_mapping_without_count_or_case_leak(self):
        source = self.review(self.save())
        self.bind(source)
        receipt, base = self.new_case()
        self.bind(source, base)
        target, mapping = self.renamed(source)
        original = self.directory.identities["editor"]
        self.directory.identities["editor"] = replace(
            original, case_keys=original.case_keys - {receipt["public_ref"]}
        )
        with self.assertRaisesMessage(cases.CaseConflict, "complete_scope"):
            services.preview(
                **self.common,
                source_version_id=source["id"],
                target_version_id=target["id"],
                mapping=mapping,
            )
        self.assertNotIn(receipt["public_ref"], str(self.state()))
        self.assertFalse(MigrationPlan.objects.exists())

    def test_new_case_facts_and_newer_binding_block_apply_and_rollback(self):
        source = self.review(self.save())
        self.bind(source)
        target, mapping = self.renamed(source)
        plan = self.review(self.plan(source, target, mapping), "PLAN")
        self.execute(plan)
        self.bind(target, additional_indices=())
        with self.assertRaisesMessage(cases.CaseConflict, "rollback_no_longer_exact"):
            self.execute(plan, "ROLLBACK")
        self.assertEqual(MigrationExecution.objects.count(), 1)

    def test_current_mapping_permission_revocation_rolls_back_execution(self):
        source = self.review(self.save())
        self.bind(source)
        target, mapping = self.renamed(source)
        plan = self.review(self.plan(source, target, mapping), "PLAN")
        real = services.seal

        def revoke(row):
            result = real(row)
            if isinstance(row, CaseClassification):
                self.authority.denied.add("MIGRATE")
            return result

        with (
            patch.object(services, "seal", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.execute(plan)
        self.assertEqual(MigrationExecution.objects.count(), 0)
        self.assertEqual(CaseClassification.objects.count(), 1)

    def test_sql_immutable_ids_and_cyclic_version_insert_are_rejected(self):
        source = self.save()
        row = TreeVersion.objects.get(pk=source["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Concept.objects.update(definition="معنى بديل")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TreeVersion.objects.filter(pk=row.pk).delete()
        nodes = [dict(item) for item in row.nodes]
        nodes[0]["parent"] = nodes[2]["id"]
        with self.assertRaises(IntegrityError), transaction.atomic():
            seal(
                TreeVersion(
                    tree=row.tree,
                    number=2,
                    previous=row,
                    nodes=nodes,
                    reason="دورة مزورة",
                    request_key=uuid.uuid4(),
                    provider_id=self.directory.provider_id,
                    subject_id="editor",
                    auth_epoch="epoch-1",
                )
            )
        self.assertEqual(TreeVersion.objects.count(), 1)

    def test_sql_incomplete_migration_cannot_commit(self):
        source = self.review(self.save())
        self.bind(source)
        target, mapping = self.renamed(source)
        plan = self.review(self.plan(source, target, mapping), "PLAN")
        with self.assertRaises(IntegrityError), transaction.atomic():
            seal(
                MigrationExecution(
                    plan_id=plan["id"],
                    kind="APPLY",
                    count=1,
                    reason="لم تنشأ الروابط",
                    request_key=uuid.uuid4(),
                    provider_id=self.directory.provider_id,
                    subject_id="editor",
                    auth_epoch="epoch-1",
                )
            )
        self.assertFalse(MigrationExecution.objects.exists())

    def test_concurrent_exact_binding_only_one_can_win(self):
        source = self.review(self.save())
        nodes = TreeVersion.objects.get(pk=source["id"]).nodes
        command = self.command()

        def save(primary):
            connections.close_all()
            try:
                try:
                    services.bind(
                        **{**command, "request_key": uuid.uuid4()},
                        version_id=source["id"],
                        primary=primary,
                        additional=[],
                        reason="تصنيف متزامن",
                        confirmed=True,
                    )
                    return "saved"
                except cases.CaseConflict:
                    return "stale"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(save, [nodes[1]["id"], nodes[3]["id"]]))
        self.assertEqual(sorted(result), ["saved", "stale"])
        self.assertEqual(CaseClassification.objects.count(), 1)

    def test_new_facts_make_old_answer_classification_historical_and_block_plan(self):
        source = self.review(self.save())
        self.bind(source)
        target, mapping = self.renamed(source)
        plan = self.review(self.plan(source, target, mapping), "PLAN")
        original_binding = CaseClassification.objects.get()
        cases.add_followup(
            token=self.receipt["token"],
            text="واقعة اصطناعية جديدة لا يجوز تجاهلها",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        self.assertFalse(self.state()["binding"]["current_answer"])
        with self.assertRaises(cases.CaseConflict):
            self.execute(plan)
        self.assertFalse(MigrationExecution.objects.exists())
        self.assertEqual(CaseClassification.objects.get().digest, original_binding.digest)

    def test_new_source_binding_after_dry_run_blocks_review_and_execution(self):
        source = self.review(self.save())
        self.bind(source)
        target, mapping = self.renamed(source)
        approved = self.review(self.plan(source, target, mapping), "PLAN")
        pending = self.plan(source, target, mapping)
        _, second = self.new_case()
        self.bind(source, second)
        with self.assertRaisesMessage(cases.CaseConflict, "impact_set_changed"):
            self.review(pending, "PLAN")
        with self.assertRaisesMessage(cases.CaseConflict, "impact_set_changed"):
            self.execute(approved)
        self.assertFalse(MigrationExecution.objects.exists())
        self.assertEqual(CaseClassification.objects.count(), 2)
