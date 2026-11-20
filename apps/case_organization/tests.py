import uuid
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import urlencode

from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import CaseEvent
from tests.casework.test_http import WEB_SETTINGS, Directory, hidden, post

from . import services
from .models import OrganizationRevision


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_CASE_ORGANIZATION_ENABLED": True,
        "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
    }
)
class OrganizationTests(TransactionTestCase):
    def setUp(self):
        self.receipt = cases.intake_case(
            original_question="  سؤال أصلي خاص بلا وسم  ",
            source_event_id="org-1",
            requester_id="org-requester",
            idempotency_key="org-1",
            synthetic_fixtures_only=True,
        )
        self.other = cases.intake_case(
            original_question="سؤال مستقل للشخص نفسه",
            source_event_id="org-2",
            requester_id="org-requester",
            idempotency_key="org-2",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"], self.other["public_ref"])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id=self.directory.current.subject_id,
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.setting = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        self.setting.enable()
        self.addCleanup(self.setting.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )

    def values(self, **changes):
        current = cases.read_case(**self.common)
        return {
            "tags": ["مسافر"],
            "question_types": ["MAKEUP", "EXPIATION"],
            "note": "ملاحظة داخلية لا تُنشر",
            "command_id": str(uuid.uuid4()),
            "expected_metadata_version": services.snapshot(**self.common)["metadata_version"],
            "expected_revision": current["revision"],
            "expected_evidence_version": current["evidence_version"],
            **changes,
        }

    def test_metadata_and_notes_preserve_approved_answer_evidence_and_original(self):
        current = cases.read_case(**self.common)
        cases.save_answer(
            **self.common,
            text="جواب بشري اصطناعي",
            expected_revision=current["revision"],
            expected_evidence_version=1,
        )
        current = cases.read_case(**self.common)
        cases.record_decision(
            **self.common,
            answer_id=current["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=current["revision"],
            expected_evidence_version=1,
        )
        before = cases.read_case(**self.common)
        count = CaseEvent.objects.count()
        result = services.save(**self.common, **self.values())
        self.assertEqual(result["metadata_version"], 1)
        self.assertEqual(result["question_types"], ["MAKEUP", "EXPIATION"])
        self.assertEqual(cases.read_case(**self.common), before)
        self.assertEqual(CaseEvent.objects.count(), count)
        independent = services.snapshot(**{**self.common, "case_id": self.other["case_id"]})
        self.assertEqual(independent["tags"], [])
        self.assertNotIn(
            "ملاحظة داخلية",
            str(cases.requester_status(token=self.receipt["token"], synthetic_fixtures_only=True)),
        )

    def test_conflicting_edit_replay_and_history_are_explicit(self):
        first = self.values()
        services.save(**self.common, **first)
        services.save(**self.common, **first)
        self.assertEqual(OrganizationRevision.objects.count(), 1)
        with self.assertRaisesRegex(cases.CaseConflict, "command_reused"):
            services.save(**self.common, **{**first, "note": "تغيير في إعادة الطلب"})
        with self.assertRaisesRegex(cases.CaseConflict, "version_changed"):
            services.save(**self.common, **{**first, "command_id": str(uuid.uuid4())})
        result = services.save(
            **self.common,
            **self.values(tags=[], question_types=[], note="أزيلت الأوصاف بعد مراجعة بشرية"),
        )
        self.assertEqual(result["tags"], [])
        self.assertEqual(result["history"][1]["tags"], ["مسافر"])
        self.assertEqual(result["metadata_version"], 2)

    def test_new_facts_reject_old_form_without_mutating_metadata(self):
        pending = self.values()
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع جديدة",
            expected_revision=pending["expected_revision"],
            synthetic_fixtures_only=True,
        )
        with self.assertRaisesRegex(cases.CaseConflict, "case_changed"):
            services.save(**self.common, **pending)
        self.assertEqual(OrganizationRevision.objects.count(), 0)

    def test_source_scope_role_epoch_and_midwrite_revocation_fail_closed(self):
        values = self.values()
        self.directory.grant(self.other["public_ref"])
        with self.assertRaises(cases.CaseConflict):
            services.save(**self.common, **values)
        self.directory.grant(self.receipt["public_ref"])
        self.directory.current = replace(self.directory.current, role="ORGANIZER_ADMIN")
        with self.assertRaises(cases.CaseConflict):
            services.snapshot(**self.common)
        self.directory.current = replace(self.directory.current, role="MUFTI")
        original = OrganizationRevision.objects.create

        def revoke(**kwargs):
            result = original(**kwargs)
            self.directory.current = replace(self.directory.current, auth_epoch="revoked")
            return result

        with patch.object(OrganizationRevision.objects, "create", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                services.save(**self.common, **values)
        self.assertEqual(OrganizationRevision.objects.count(), 0)

    def test_explicit_search_filters_no_inferred_tags_or_notes_in_results(self):
        common = {key: value for key, value in self.common.items() if key != "case_id"}
        self.assertEqual(len(services.search(**common, query="سؤال")), 2)
        services.save(**self.common, **self.values())
        result = services.search(**common, tag="مسافر", question_type="EXPIATION")
        self.assertEqual([r["public_ref"] for r in result], [self.receipt["public_ref"]])
        self.assertNotIn("ملاحظة داخلية", str(result))
        self.assertEqual(services.search(**common, tag="مقيم"), [])
        self.directory.grant(self.other["public_ref"])
        self.assertEqual(services.search(**common, tag="مسافر"), [])

    def test_bad_values_and_database_history_tampering_rejected(self):
        for changes in (
            {"tags": ["x"] * 2},
            {"tags": [1]},
            {"tags": ["x\x00"]},
            {"tags": ["x" * 49]},
            {"question_types": ["GUESSED"]},
            {"question_types": ["MAKEUP", "MAKEUP"]},
            {"expected_metadata_version": True},
            {"note": "x" * 2001},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                services.save(**self.common, **self.values(**changes))
        services.save(**self.common, **self.values())
        for operation in (
            lambda: OrganizationRevision.objects.update(note="rewrite"),
            lambda: OrganizationRevision.objects.all().delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def page(self):
        login = self.client.get("/casework/staff/login/")
        self.assertEqual(
            post(
                self.client,
                "/casework/staff/login/",
                {"credential": self.directory.credential},
                login,
            ).status_code,
            303,
        )
        return post(
            self.client,
            "/casework/staff/",
            {"action": "organization_open", "case_ref": self.receipt["public_ref"]},
            self.client.get("/casework/staff/"),
        )

    def form(self, page):
        return {
            key: hidden(page, key)
            for key in (
                "csrfmiddlewaretoken",
                "case_ref",
                "revision",
                "evidence_version",
                "metadata_version",
                "command_id",
            )
        } | {
            "action": "organization_save",
            "tags": "مسافر\nمريض",
            "question_types": ["MAKEUP", "EXPIATION"],
            "note": "ملاحظة داخلية",
        }

    def submit(self, fields):
        return self.client.post(
            "/casework/staff/",
            urlencode(fields, doseq=True),
            content_type="application/x-www-form-urlencoded",
        )

    def test_native_editor_multiple_types_and_stale_recovery_no_private_leak(self):
        page = self.page()
        self.assertEqual(page.status_code, 200, page.content)
        fields = self.form(page)
        good = self.submit(fields)
        self.assertEqual(good.status_code, 200, good.content)
        stale = self.submit({**fields, "command_id": str(uuid.uuid4()), "note": "محاولة متأخرة"})
        self.assertEqual(stale.status_code, 409)
        self.assertContains(stale, "محاولة متأخرة", status_code=409)
        self.assertEqual(OrganizationRevision.objects.count(), 1)
        self.directory.grant(self.other["public_ref"])
        denied = self.submit(fields)
        self.assertIn(denied.status_code, (403, 404))
        self.assertNotIn("ملاحظة داخلية".encode(), denied.content)

    def test_native_form_csrf_duplicates_extra_fields_and_closed_flag(self):
        fields = self.form(self.page())
        for changes, status in (
            ({"role": "MUFTI"}, 400),
            ({"tags": ["a", "b"]}, 400),
            ({"csrfmiddlewaretoken": ""}, 403),
        ):
            self.assertEqual(self.submit({**fields, **changes}).status_code, status)
        with override_settings(FATWA_CASE_ORGANIZATION_ENABLED=False):
            self.assertEqual(self.submit(fields).status_code, 404)
        self.assertEqual(OrganizationRevision.objects.count(), 0)

    def test_maintenance_blocks_new_metadata_writes(self):
        from apps.platform_recovery.integration import MaintenanceUnavailable

        with override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True, FATWA_RECOVERY_MAINTENANCE_ROOT=None
        ):
            with self.assertRaises(MaintenanceUnavailable):
                services.save(
                    **self.common,
                    tags=[],
                    question_types=[],
                    note="closed",
                    command_id=str(uuid.uuid4()),
                    expected_metadata_version=0,
                    expected_revision=1,
                    expected_evidence_version=1,
                )
        self.assertEqual(OrganizationRevision.objects.count(), 0)

    def test_refreshed_identity_expiry_preserves_stable_authority(self):
        from tests.casework.test_core import TestDirectory

        directory = TestDirectory([self.receipt["public_ref"]])
        common = {**self.common, "subject_id": "synthetic-mufti", "provider": directory}
        values = self.values()
        # TestDirectory gives a fresh valid_until on every resolve by design.
        result = services.save(**common, **values)
        self.assertEqual(result["metadata_version"], 1)
        self.assertEqual(services.snapshot(**common)["tags"], ["مسافر"])
        rows = services.search(**{k: v for k, v in common.items() if k != "case_id"}, tag="مسافر")
        self.assertEqual([row["public_ref"] for row in rows], [self.receipt["public_ref"]])

    def test_provider_change_after_insert_rolls_back_metadata(self):
        values = self.values()
        create = OrganizationRevision.objects.create

        def changed(**kwargs):
            result = create(**kwargs)
            self.directory.provider_id = "changed-provider"
            return result

        with patch.object(OrganizationRevision.objects, "create", side_effect=changed):
            with self.assertRaisesRegex(cases.CaseConflict, "identity_changed"):
                services.save(**self.common, **values)
        self.assertEqual(OrganizationRevision.objects.count(), 0)

    def test_native_form_accepts_all_seventeen_explicit_question_types(self):
        fields = self.form(self.page())
        fields["question_types"] = list(services.QUESTION_TYPES)
        response = self.submit(fields)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            OrganizationRevision.objects.get().question_types, list(services.QUESTION_TYPES)
        )
        self.assertEqual(sum(item["selected"] for item in response.context["types"]), 17)
