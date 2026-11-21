"""Operational metadata writes remain separate from original content and scholarly authority."""

import uuid
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from apps.case_organization import services as organization
from apps.case_organization.models import OrganizationRevision
from apps.casework import services as cases
from apps.development_taxonomy import services as taxonomy
from apps.development_taxonomy.models import CaseClassification
from tests.casework.test_http import hidden, post

from . import metadata, services, views
from .metadata_test_support import METADATA_FEATURES, ClassificationAuthority, MetadataFixture
from .test_support import CREDENTIALS

BASE = "/casework/operations/"


@override_settings(**METADATA_FEATURES)
class OperationalMetadataTests(MetadataFixture, TransactionTestCase):
    def test_real_organizer_updates_tags_types_and_reviewed_classification_visible_to_mufti(self):
        original_note = OrganizationRevision.objects.get(case_id=self.target["case_id"]).note
        self.update_metadata()
        self.update_metadata(field="question_types", values=["RULING", "TIME"])
        result = self.classify()
        history = list(
            OrganizationRevision.objects.filter(case_id=self.target["case_id"]).order_by("version")
        )
        self.assertEqual([row.note for row in history], [original_note, "", ""])
        self.assertEqual([row.subject_id for row in history], ["mufti", "operator", "operator"])
        self.assertEqual(result["role"], "ORGANIZER")
        self.assertTrue(result["current_classification"]["current"])
        mufti = dict(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(organization.snapshot(**mufti)["tags"], ["وسم من المنظم"])
        self.assertEqual(taxonomy.desk(**mufti)["binding"]["actor"], "operator")
        self.assertEqual(self.immutable_metadata_sources(), self.metadata_originals)
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                **self.common,
                case_id=self.target["case_id"],
                text="غير مخول",
                expected_revision=3,
                expected_evidence_version=1,
            )

    def test_each_field_and_classification_grant_is_independent_for_actual_roles(self):
        self.authority.revoke(action="EDIT_TAGS")
        with self.assertRaises(cases.CaseConflict):
            self.update_metadata()
        self.update_metadata(field="question_types", values=["TIME"])
        self.authority.revoke(action="BIND_CLASSIFICATION")
        with self.assertRaises(cases.CaseConflict):
            self.classify()
        with metadata.projection(case_ref=self.target["public_ref"], **self.common) as result:
            self.assertFalse(result["can_edit_tags"])
            self.assertTrue(result["can_edit_types"])
            self.assertFalse(result["classifications"][0]["can_bind"])
        self.authority.revoke(subject="admin", action="EDIT_TAGS")
        with self.assertRaises(cases.CaseConflict):
            with metadata.update(
                **{**self.common, "subject_id": "admin"}, **self.metadata_values()
            ):
                pass
        self.assertEqual(self.immutable_metadata_sources(), self.metadata_originals)

    def test_scope_read_feature_and_domain_grants_are_all_current(self):
        before = self.state()
        self.authority.revoke(action="READ_METADATA")
        with self.assertRaises(cases.CaseConflict):
            self.update_metadata()
        for key in ("hidden", "unscoped"):
            with self.assertRaises(cases.CaseConflict):
                with metadata.projection(case_ref=self.receipts[key]["public_ref"], **self.common):
                    pass
        for name in ("FATWA_OPERATIONAL_METADATA_ENABLED", "FATWA_CASE_ORGANIZATION_ENABLED"):
            with override_settings(**{name: False}), self.assertRaises(cases.CaseConflict):
                with metadata.projection(case_ref=self.target["public_ref"], **self.common):
                    pass
        self.assertEqual(self.state(), before)

    def test_denied_version_and_tree_scope_do_not_expose_labels_or_allow_binding(self):
        self.classification_authority.grants = {
            row
            for row in self.classification_authority.grants
            if not (row[0] == "operator" and row[2] == "READ")
        }
        with metadata.projection(case_ref=self.target["public_ref"], **self.common) as result:
            self.assertEqual(result["classifications"], [])
        self.authority.revoke(action="READ_CASE", case_ref=self.receipts["tree"]["public_ref"])
        with self.assertRaises(cases.CaseConflict):
            self.classify()
        self.assertEqual(self.state(), self.originals)

    def test_invalid_fields_cas_pins_and_classification_selections_do_not_write(self):
        for changes in (
            {"expected_metadata_version": 0},
            {"expected_revision": 1},
            {"values": ["duplicate", "duplicate"]},
            {"field": "note"},
            {"field": "question_types", "values": ["NEW_ROLE"]},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.update_metadata(**changes)
        for changes in (
            {"version_digest": "0" * 64},
            {"expected_classification_version": 1},
            {"expected_evidence_version": 2},
            {"confirmed": False},
            {"primary": str(uuid.uuid4())},
            {"additional": [self.version.nodes[1]["id"]]},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.classify(**changes)
        self.assertEqual(self.state(), self.originals)

    def test_metadata_and_binding_retries_recheck_grants_and_conflict_on_changed_input(self):
        values = self.metadata_values()
        for _ in range(2):
            with metadata.update(**self.common, **values):
                pass
        self.assertEqual(
            OrganizationRevision.objects.filter(case_id=self.target["case_id"]).count(), 2
        )
        with self.assertRaises(cases.CaseConflict):
            with metadata.update(**self.common, **{**values, "values": ["تغيير بنفس المفتاح"]}):
                pass
        command = self.classification_values()
        for _ in range(2):
            with metadata.bind_classification(**self.common, **command):
                pass
        self.assertEqual(
            CaseClassification.objects.filter(case_id=self.target["case_id"]).count(), 1
        )
        with self.assertRaises(cases.CaseConflict):
            with metadata.bind_classification(**self.common, **{**command, "reason": "سبب مختلف"}):
                pass
        self.authority.revoke(action="BIND_CLASSIFICATION")
        with self.assertRaises(cases.CaseConflict):
            with metadata.bind_classification(**self.common, **command):
                pass
        self.assertEqual(self.immutable_metadata_sources(), self.metadata_originals)

    def test_late_domain_policy_replacement_after_dto_discards_pending_write(self):
        original = settings.FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY
        try:
            with self.assertRaises(cases.CaseConflict):
                with metadata.bind_classification(**self.common, **self.classification_values()):
                    replacement = ClassificationAuthority()
                    replacement.grants = set(self.classification_authority.grants)
                    replacement.binding_reads = set(self.classification_authority.binding_reads)
                    settings.FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY = replacement
        finally:
            settings.FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY = original
        self.assertEqual(self.state(), self.originals)
        with self.assertRaises(cases.CaseConflict):
            with metadata.update(**self.common, **self.metadata_values()):
                self.directory.identities["operator"] = replace(
                    self.directory.identities["operator"], active=False
                )
        self.assertEqual(self.state(), self.originals)

    def test_unrelated_append_inside_persistence_is_not_adopted_by_source_fingerprint(self):
        original = organization._append_locked

        def append_then_extra(**kwargs):
            result = original(**kwargs)
            organization.save(
                case_id=self.target["case_id"],
                subject_id="mufti",
                provider=self.directory,
                tags=["كتابة جانبية يجب ردها"],
                question_types=["TIME"],
                note="",
                command_id=uuid.uuid4(),
                expected_metadata_version=2,
                expected_revision=3,
                expected_evidence_version=1,
                synthetic_fixtures_only=True,
            )
            return result

        # Patch only the operational call site; recursive Mufti writes use the original primitive.
        def once(**kwargs):
            with patch.object(organization, "_append_locked", original):
                return append_then_extra(**kwargs)

        with (
            patch.object(organization, "_append_locked", once),
            self.assertRaises(cases.CaseConflict),
        ):
            self.update_metadata()
        self.assertEqual(self.state(), self.originals)

    def login(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get(BASE + "login/")
        self.assertEqual(
            post(
                client, BASE + "login/", {"credential": CREDENTIALS["operator"]}, page
            ).status_code,
            303,
        )
        page = client.get(BASE)
        self.assertContains(page, 'id="ops-metadata-index"')
        return client, post(
            client, BASE, {"action": "metadata_editor", "case_ref": self.target["public_ref"]}, page
        )

    def native(self, client, page, fields):
        pairs = [("csrfmiddlewaretoken", hidden(page, "csrfmiddlewaretoken"))]
        for key, value in fields.items():
            pairs.extend((key, item) for item in value) if isinstance(
                value, list
            ) else pairs.append((key, value))
        return client.post(BASE, urlencode(pairs), content_type="application/x-www-form-urlencoded")

    def test_native_forms_write_actual_organizer_metadata_and_keep_notes_private(self):
        client, page = self.login()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertNotContains(page, "ملاحظة داخلية لا تعرضها قائمة التشغيل")

        def pins(response):
            return {
                key: hidden(response, key)
                for key in (
                    "case_ref",
                    "revision",
                    "evidence_version",
                    "metadata_version",
                    "command_id",
                )
            }

        page = self.native(
            client,
            page,
            {
                **pins(page),
                "action": "metadata_tags",
                "tags": "وسم من المتصفح\n<script>نص</script>",
            },
        )
        self.assertContains(page, "&lt;script&gt;نص&lt;/script&gt;")
        page = self.native(
            client,
            page,
            {**pins(page), "action": "metadata_types", "question_types": ["RULING", "TIME"]},
        )
        self.assertEqual(page.status_code, 200, page.content)
        fields = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "revision",
                "evidence_version",
                "classification_version",
                "command_id",
                "version_id",
                "version_digest",
            )
        }
        page = self.native(
            client,
            page,
            {
                **fields,
                "action": "metadata_classify",
                "primary": self.version.nodes[1]["id"],
                "additional": [self.version.nodes[3]["id"]],
                "reason": "تصنيف أصلي من واجهة التشغيل",
                "confirmed": "yes",
            },
        )
        self.assertContains(page, 'id="ops-classification-current"')
        self.assertContains(page, "ORGANIZER")
        self.assertIn("no-store", page["Cache-Control"])
        self.assertEqual(self.immutable_metadata_sources(), self.metadata_originals)

    def test_native_forgery_csrf_and_render_time_revocation_leave_no_partial_write(self):
        client, page = self.login()
        fields = {
            key: hidden(page, key)
            for key in (
                "case_ref",
                "revision",
                "evidence_version",
                "metadata_version",
                "command_id",
            )
        }
        fields.update(action="metadata_tags", tags="لا يحفظ")
        self.assertEqual(client.post(BASE, fields).status_code, 403)
        for extra in ({"role": "MUFTI"}, {"note": "تجاوز"}, {"question_types": ["TIME"]}):
            self.assertEqual(self.native(client, page, {**fields, **extra}).status_code, 409)
        render = views.render

        def revoke_after_render(*args, **kwargs):
            response = render(*args, **kwargs)
            self.authority.revoke(action="EDIT_TAGS")
            return response

        with patch.object(views, "render", revoke_after_render):
            self.assertEqual(self.native(client, page, fields).status_code, 409)
        self.assertEqual(self.state(), self.originals)

    def test_completed_case_keeps_native_metadata_entry_without_pending_count_inflation(self):
        self.update_metadata()
        self.classify()
        with services.queue_projection(**self.common) as queue:
            self.assertIn(
                self.target["public_ref"], [row["public_ref"] for row in queue["metadata_cases"]]
            )
            self.assertNotIn(
                self.target["public_ref"], [row["public_ref"] for row in queue["rows"]]
            )
