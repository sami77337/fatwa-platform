"""Actual campaign forms for tree versions, case bindings and reviewed rollback."""

import uuid
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, TransactionTestCase, override_settings

from tests.casework.test_http import hidden, post

from . import editor, services
from .models import CaseClassification, MigrationExecution, MigrationPlan, TreeVersion
from .test_support import FEATURES, TaxonomyFixture, initial_nodes


@override_settings(**FEATURES)
class DevelopmentTaxonomyHTTPTests(TaxonomyFixture, TransactionTestCase):
    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        name = {"editor": "editor", "other": "reviewer"}[subject]
        response = post(
            client,
            "/casework/staff/login/",
            {"credential": f"synthetic-{name}-credential-32-characters"},
            page,
        )
        self.assertEqual(response.status_code, 303)
        return client, client.get("/casework/staff/")

    def action(self, client, page, action="dt_open", **values):
        data = {
            "action": action,
            "case_ref": self.receipt["public_ref"],
            "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
            **values,
        }
        return client.post(
            "/casework/staff/",
            urlencode(data, doseq=True),
            content_type="application/x-www-form-urlencoded",
        )

    def save_native(self, client, page, nodes, **changes):
        values = dict(
            state=hidden(page, "state"),
            command="save",
            title="شجرة واجهة اصطناعية",
            provenance="تعريفات اصطناعية للتطوير بلا اعتماد علمي نهائي",
            node_key=[row["key"] for row in nodes],
            node_name=[row["name"] for row in nodes],
            node_parent=[row["parent"] for row in nodes],
            node_definition=[row["definition"] for row in nodes],
            reason="إنشاء نسخة موثقة عبر النموذج",
            confirmed="yes",
        )
        response = self.action(client, page, "dt_save", **(values | changes))
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def review_native(self, client, page, identifier, kind="VERSION"):
        response = self.action(
            client,
            page,
            "dt_review",
            state=hidden(page, "state"),
            target_kind=kind,
            target_id=identifier,
            decision="APPROVE",
            reason="مراجعة مستقلة للنسخة أو الخطة المحددة",
            confirmed="yes",
            **({"version_id": identifier} if kind == "VERSION" else {}),
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def test_native_create_review_primary_additional_map_apply_and_rollback(self):
        client, home = self.login()
        page = self.action(client, home)
        self.assertEqual(page.status_code, 200, page.content)
        page = self.save_native(client, page, initial_nodes())
        source = TreeVersion.objects.get()
        self.assertContains(page, 'id="dt-outline"')
        self.assertNotContains(page, 'id="dt-version-review"')
        reviewer, home2 = self.login("other")
        review_page = self.action(reviewer, home2, version_id=str(source.pk))
        self.review_native(reviewer, review_page, str(source.pk))
        page = self.action(client, page, version_id=str(source.pk))
        page = self.action(
            client,
            page,
            "dt_bind",
            state=hidden(page, "state"),
            version_id=str(source.pk),
            primary=source.nodes[1]["id"],
            additional=[source.nodes[3]["id"]],
            reason="مسألة مركبة ذات بابين",
            confirmed="yes",
        )
        self.assertContains(page, "التصنيف الرئيسي: باب اصطناعي ألف")
        rows = self.nodes({"id": str(source.pk)})
        rows[1]["name"] = "باب ألف بعد تصحيح الاسم"
        rows[2]["parent"] = rows[3]["key"]
        page = self.save_native(client, page, rows, version_id=str(source.pk))
        target = TreeVersion.objects.get(number=2)
        review_page = self.action(reviewer, review_page, version_id=str(target.pk))
        self.review_native(reviewer, review_page, str(target.pk))
        page = self.action(client, page)
        mapped = self.action(
            client,
            page,
            "dt_prepare",
            state=hidden(page, "state"),
            command="choose",
            source_version_id=str(source.pk),
            target_version_id=str(target.pk),
        )
        self.assertContains(mapped, 'id="dt-mapping"')
        values = {}
        for index, row in enumerate(source.nodes):
            values["map_kind_" + row["id"]] = (
                "RENAMED" if index == 1 else "MOVED" if index == 2 else "SAME"
            )
            values["map_target_" + row["id"]] = [row["id"]]
            values["map_reason_" + row["id"]] = "هوية ثابتة ومعنى محفوظ"
        impact = self.action(
            client,
            mapped,
            "dt_prepare",
            state=hidden(mapped, "state"),
            command="impact",
            source_version_id=str(source.pk),
            target_version_id=str(target.pk),
            **values,
        )
        self.assertContains(impact, 'id="dt-impact"')
        case = self.receipt["case_id"]
        planned = self.action(
            client,
            impact,
            "dt_prepare",
            state=hidden(impact, "state"),
            command="plan",
            impact=hidden(impact, "impact"),
            reason="خطة فعلية لروابط التصنيف",
            confirmed="yes",
            **{
                "resolution_primary_" + case: source.nodes[1]["id"],
                "resolution_additional_" + case: [source.nodes[3]["id"]],
                "resolution_reason_" + case: "نقل راجعت أثره على هذه الفتوى",
            },
        )
        self.assertEqual(planned.status_code, 200, planned.content)
        plan = MigrationPlan.objects.get()
        self.assertEqual(CaseClassification.objects.count(), 1)
        review_page = self.action(reviewer, review_page)
        self.review_native(reviewer, review_page, str(plan.pk), "PLAN")
        page = self.action(client, planned)
        applied = self.action(
            client,
            page,
            "dt_apply",
            state=hidden(page, "state"),
            plan_id=str(plan.pk),
            reason="تطبيق بعد مراجعة مستقلة",
            confirmed="yes",
        )
        self.assertContains(applied, "التصنيف الرئيسي: باب ألف بعد تصحيح الاسم")
        rolled = self.action(
            client,
            applied,
            "dt_rollback",
            state=hidden(applied, "state"),
            plan_id=str(plan.pk),
            reason="عكس الروابط المحددة وحفظ التاريخ",
            confirmed="yes",
        )
        self.assertContains(rolled, "التصنيف الرئيسي: باب اصطناعي ألف")
        self.assertEqual(CaseClassification.objects.count(), 3)
        self.assertEqual(MigrationExecution.objects.count(), 2)
        self.assertIn("no-store", rolled["Cache-Control"])
        self.assertIn("noindex", rolled["X-Robots-Tag"])

    def test_campaign_budget_accepts_largest_tree_and_mapping_without_test_override(self):
        from django.conf import settings

        from config.settings import campaign_review

        self.assertNotIn("DATA_UPLOAD_MAX_NUMBER_FIELDS", FEATURES)
        self.assertEqual(
            settings.DATA_UPLOAD_MAX_NUMBER_FIELDS, campaign_review.DATA_UPLOAD_MAX_NUMBER_FIELDS
        )
        self.assertGreaterEqual(settings.DATA_UPLOAD_MAX_NUMBER_FIELDS, 456)
        client, home = self.login()
        page = self.action(client, home)
        nodes = [
            {
                "key": f"new:{index}",
                "parent": "",
                "name": f"عنوان مصدر اصطناعي {index}",
                "definition": f"تعريف مستقل اصطناعي {index}",
            }
            for index in range(64)
        ]
        # This is the actual native tree payload: 64 four-column rows and
        # ten fixed fields, not a test-only increase of Django's parser limit.
        page = self.save_native(client, page, nodes, version_id="")
        source_row = TreeVersion.objects.get()
        source = {"id": str(source_row.pk), "tree_id": str(source_row.tree_id), "number": 1}
        self.review(source)
        target = self.review(self.save(nodes[:4], tree=source))
        target_row = TreeVersion.objects.get(pk=target["id"])
        page = self.action(client, page)
        mapped = self.action(
            client,
            page,
            "dt_prepare",
            state=hidden(page, "state"),
            command="choose",
            source_version_id=source["id"],
            target_version_id=target["id"],
        )
        self.assertEqual(mapped.status_code, 200, mapped.content)
        fields = {
            "state": hidden(mapped, "state"),
            "command": "impact",
            "source_version_id": source["id"],
            "target_version_id": target["id"],
        }
        for row in source_row.nodes:
            fields["map_kind_" + row["id"]] = "SPLIT"
            fields["map_target_" + row["id"]] = [node["id"] for node in target_row.nodes]
            fields["map_reason_" + row["id"]] = "أربع وجهات صريحة لهذا المعنى الاصطناعي"
        self.assertEqual(
            3 + sum(len(v) if isinstance(v, list) else 1 for v in fields.values()), 391
        )
        forged = self.action(
            client,
            mapped,
            "dt_prepare",
            **fields,
            **{"map_reason_" + str(uuid.uuid4()): "حقل معرّف غير موجود لا يجوز تجاهله"},
        )
        self.assertEqual(forged.status_code, 409)
        impact = self.action(client, mapped, "dt_prepare", **fields)
        self.assertContains(impact, 'id="dt-impact"')
        self.assertFalse(MigrationPlan.objects.exists())

    def test_campaign_budget_accepts_all_32_cases_with_12_additional_choices(self):
        source = self.review(
            self.save(
                [
                    {
                        "key": f"new:{index}",
                        "parent": "",
                        "name": f"تصنيف اصطناعي {index}",
                        "definition": f"معنى مستقل اصطناعي {index}",
                    }
                    for index in range(13)
                ]
            )
        )
        additional_indices = tuple(range(1, 13))
        self.bind(source, primary_index=0, additional_indices=additional_indices)
        receipts = [self.receipt]
        for _ in range(31):
            receipt, base = self.new_case()
            self.bind(source, base, primary_index=0, additional_indices=additional_indices)
            receipts.append(receipt)
        target, mapping = self.renamed(source)
        source_row = TreeVersion.objects.get(pk=source["id"])
        client, home = self.login()
        page = self.action(client, home)
        fields = {
            "state": hidden(page, "state"),
            "command": "impact",
            "source_version_id": source["id"],
            "target_version_id": target["id"],
        }
        for row in mapping:
            fields["map_kind_" + row["source"]] = row["kind"]
            fields["map_target_" + row["source"]] = row["targets"]
            fields["map_reason_" + row["source"]] = row["reason"]
        impact = self.action(client, page, "dt_prepare", **fields)
        self.assertContains(impact, 'id="dt-impact"')
        fields = {
            "state": hidden(impact, "state"),
            "command": "plan",
            "impact": hidden(impact, "impact"),
            "reason": "كل القضايا الاثنتين والثلاثين لها اختيار بشري صريح",
            "confirmed": "yes",
        }
        for receipt in receipts:
            identifier = receipt["case_id"]
            fields["resolution_primary_" + identifier] = source_row.nodes[0]["id"]
            fields["resolution_additional_" + identifier] = [
                source_row.nodes[index]["id"] for index in additional_indices
            ]
            fields["resolution_reason_" + identifier] = "اختيار رئيسي واثنا عشر تصنيفًا إضافيًا"
        self.assertEqual(
            3 + sum(len(v) if isinstance(v, list) else 1 for v in fields.values()), 456
        )
        forged = self.action(
            client,
            impact,
            "dt_prepare",
            **fields,
            **{"resolution_reason_" + str(uuid.uuid4()): "قضية ليست ضمن الأثر"},
        )
        self.assertEqual(forged.status_code, 409)
        planned = self.action(client, impact, "dt_prepare", **fields)
        self.assertEqual(planned.status_code, 200, planned.content)
        self.assertEqual(len(MigrationPlan.objects.get().manifest), 32)
        self.assertEqual(CaseClassification.objects.count(), 32)
        self.assertFalse(MigrationExecution.objects.exists())

    def test_csrf_cross_actor_and_stale_form_are_rejected(self):
        client, home = self.login()
        page = self.action(client, home)
        self.assertEqual(
            client.post(
                "/casework/staff/", {"action": "dt_open", "case_ref": self.receipt["public_ref"]}
            ).status_code,
            403,
        )
        other, home2 = self.login("other")
        opened = self.action(other, home2)
        denied = self.action(
            other,
            opened,
            "dt_prepare",
            state=hidden(page, "state"),
            command="choose",
            source_version_id=str(uuid.uuid4()),
            target_version_id=str(uuid.uuid4()),
        )
        self.assertEqual(denied.status_code, 409)
        self.save()
        rows = initial_nodes()
        denied = self.action(
            client,
            page,
            "dt_save",
            state=hidden(page, "state"),
            command="save",
            title="نسخة قديمة",
            provenance="سجل اصطناعي",
            node_key=[row["key"] for row in rows],
            node_name=[row["name"] for row in rows],
            node_parent=[row["parent"] for row in rows],
            node_definition=[row["definition"] for row in rows],
            reason="حفظ متأخر",
            confirmed="yes",
        )
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(TreeVersion.objects.count(), 1)

    def test_late_render_revocation_rolls_back_saved_version(self):
        client, home = self.login()
        page = self.action(client, home)
        real = editor.render

        def revoke(*args, **kwargs):
            response = real(*args, **kwargs)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], active=False
            )
            return response

        rows = initial_nodes()
        with patch.object(editor, "render", side_effect=revoke):
            response = self.action(
                client,
                page,
                "dt_save",
                state=hidden(page, "state"),
                command="save",
                title="لن تبقى هذه النسخة",
                provenance="سجل اصطناعي",
                node_key=[row["key"] for row in rows],
                node_name=[row["name"] for row in rows],
                node_parent=[row["parent"] for row in rows],
                node_definition=[row["definition"] for row in rows],
                reason="اختبار ذرية الرد",
                confirmed="yes",
            )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(TreeVersion.objects.exists())
        self.assertNotIn("لن تبقى هذه النسخة".encode(), response.content)

    def test_render_history_phantom_is_not_accepted_after_last_read(self):
        source = self.review(self.save())
        self.bind(source)
        client, home = self.login()
        page = self.action(client, home)
        real = editor.render

        def change(*args, **kwargs):
            response = real(*args, **kwargs)
            services.bind(
                **self.command(),
                version_id=source["id"],
                primary=TreeVersion.objects.get(pk=source["id"]).nodes[3]["id"],
                additional=[],
                reason="تغيير خلال توليد الرد",
                confirmed=True,
            )
            return response

        with patch.object(editor, "render", side_effect=change):
            response = self.action(client, page, version_id=source["id"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(CaseClassification.objects.count(), 1)
