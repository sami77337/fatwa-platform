"""Actual authorized source transfers and fresh canonical identity mapping."""

import json
import uuid
from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.research_library import services as library
from apps.research_library.models import LibraryDecision, LibraryVersion
from apps.research_library.test_support import payload, video
from tests.casework.test_http import hidden

from . import formats, roundtrip, services
from .models import ImportPlan, RoundtripReceipt
from .tests import FEATURES, FixtureAuthority, ImportFixture, post


@override_settings(**FEATURES)
class RoundtripTests(ImportFixture, TransactionTestCase):
    def exportable(self, external_id="roundtrip-a", raw=b"synthetic source bytes\r\n"):
        record = self.write(
            namespace="synthetic-import",
            external_id=external_id,
            payload=payload(recorded_text="سطر اصطناعي حرفي\r\nسطر ثانٍ"),
            file_bytes=raw,
            filename="source.txt",
            media_type="text/plain",
        )
        return self.approve(record, uses=["EXPORT"])

    def export(self, records):
        preview = roundtrip.prepare(**self.common, selected=[roundtrip.pin(row) for row in records])
        key = uuid.uuid4()
        result = roundtrip.download(
            **self.common,
            selected=preview["selected"],
            prepared_at=preview["prepared_at"],
            expected_sha256=preview["sha256"],
            request_key=key,
        )
        repeated = roundtrip.download(
            **self.common,
            selected=preview["selected"],
            prepared_at=preview["prepared_at"],
            expected_sha256=preview["sha256"],
            request_key=key,
        )
        self.assertEqual(result["raw"], repeated["raw"])
        return result, preview

    def import_packet(self, result, common):
        parsed = formats.parse(result["raw"], result["filename"])
        batch = services.stage(
            **common,
            raw=result["raw"],
            filename=result["filename"],
            namespace=parsed.origin["namespace"],
            provenance="حزمة مصادر اصطناعية محددة",
            rights_basis="وصف المصدر لا ينقل صلاحياته",
            request_key=uuid.uuid4(),
        )
        batch = services.configure(
            **common,
            batch_id=batch["id"],
            mapping=formats.default_mapping(parsed),
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )
        batch = services.prepare_plan(
            **common,
            batch_id=batch["id"],
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )
        batch = services.decide(
            **{**common, "subject_id": "other"},
            batch_id=batch["id"],
            plan_id=batch["plan"]["id"],
            verdict="APPROVE",
            note="راجع مستقل",
            verification_note="فحص البصمات وهويات المصدر الاصطناعي",
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )
        return services.apply_batch(
            **common,
            batch_id=batch["id"],
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )

    def test_actual_zip_roundtrip_fresh_case_keeps_source_bytes_payload_and_maps_local_ids(self):
        source = self.exportable()
        hidden = self.write(
            namespace="synthetic-import",
            external_id="not-selected",
            payload=payload(title="غير محدد في الحزمة"),
        )
        result, preview = self.export([source])
        parsed = formats.parse(result["raw"], result["filename"])
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.origin["mapping"][0]["source_item_id"], source["item_id"])
        self.assertNotIn(hidden["version_id"].encode(), result["raw"])
        for forbidden in (
            b"auth_epoch",
            b"subject_id",
            b"approval",
            b"private_question",
            b"credential",
        ):
            self.assertNotIn(forbidden, result["raw"])
        receipt = cases.intake_case(
            original_question="قضية هدف اصطناعية مستقلة",
            source_event_id=uuid.uuid4().hex,
            requester_id="roundtrip-target",
            idempotency_key=uuid.uuid4().hex,
            synthetic_fixtures_only=True,
        )
        self.directory.identities = {
            key: replace(value, case_keys=value.case_keys | {receipt["public_ref"]})
            for key, value in self.directory.identities.items()
        }
        self.authority.refs.add(receipt["public_ref"])
        target_base = {**self.common, "case_id": receipt["case_id"]}
        with override_settings(
            FATWA_MATERIAL_IMPORT_AUTHORITY=FixtureAuthority(receipt["public_ref"])
        ):
            batch = self.import_packet(result, target_base)
            self.assertEqual(batch["state"], "APPLIED")
            target = library.current_material(
                **target_base, namespace="synthetic-import", external_id="roundtrip-a"
            )
            self.assertEqual(target["payload"], source["payload"])
            self.assertEqual(target["file"], source["file"])
            self.assertNotEqual(target["item_id"], source["item_id"])
            self.assertNotEqual(target["version_id"], source["version_id"])
            self.assertEqual((target["state"], target["action_count"]), ("DRAFT", 0))
            self.assertEqual(
                LibraryDecision.objects.filter(version__item__case_id=receipt["case_id"]).count(), 0
            )
            with self.assertRaises(cases.CaseConflict):
                library.file_content(**target_base, version_id=target["version_id"], usage="EXPORT")
        self.assertEqual(preview["size"], len(result["raw"]))
        self.assertEqual(RoundtripReceipt.objects.count(), 1)

    def test_same_case_roundtrip_skips_exact_source_without_new_version_or_grant(self):
        source = self.exportable()
        result, _ = self.export([source])
        decisions = LibraryDecision.objects.count()
        batch = self.import_packet(result, self.common)
        self.assertEqual(batch["state"], "APPLIED")
        self.assertEqual(batch["results"][0]["outcomes"][0]["action"], "SKIP")
        self.assertEqual(
            (LibraryVersion.objects.count(), LibraryDecision.objects.count()), (1, decisions)
        )

    def test_actual_decoded_video_export_and_fresh_case_reimport_preserve_every_byte(self):
        original = video()
        source = self.approve(
            self.write(
                namespace="synthetic-import",
                external_id="video-a",
                payload=payload("VIDEO", title="فيديو اصطناعي محدد للتبادل"),
                file_bytes=original,
                filename="source.webm",
                media_type="video/webm",
            ),
            uses=["EXPORT"],
        )
        result, preview = self.export([source])
        parsed = formats.parse(result["raw"], result["filename"])
        self.assertEqual(parsed.rows[0]["kind"], "VIDEO")
        self.assertEqual(parsed.files[parsed.rows[0]["file_member"]].raw, original)
        self.assertEqual(preview["manifest"]["files"][0]["sha256"], source["file"]["sha256"])
        target_case = cases.intake_case(
            original_question="هدف اصطناعي لتبادل الفيديو",
            source_event_id=uuid.uuid4().hex,
            requester_id="video-target",
            idempotency_key=uuid.uuid4().hex,
            synthetic_fixtures_only=True,
        )
        self.directory.identities = {
            key: replace(value, case_keys=value.case_keys | {target_case["public_ref"]})
            for key, value in self.directory.identities.items()
        }
        self.authority.refs.add(target_case["public_ref"])
        target_base = {**self.common, "case_id": target_case["case_id"]}
        with override_settings(
            FATWA_MATERIAL_IMPORT_AUTHORITY=FixtureAuthority(target_case["public_ref"])
        ):
            imported = self.import_packet(result, target_base)
            self.assertEqual(imported["state"], "APPLIED")
            target = library.current_material(
                **target_base, namespace="synthetic-import", external_id="video-a"
            )
            self.assertEqual(target["payload"], source["payload"])
            self.assertEqual(target["file"], source["file"])
            self.assertNotEqual(target["version_id"], source["version_id"])
            self.assertEqual((target["state"], target["action_count"]), ("DRAFT", 0))
            with self.assertRaises(cases.CaseConflict):
                library.file_content(**target_base, version_id=target["version_id"], usage="EXPORT")

    def test_both_runtime_export_permission_and_reviewed_exact_use_are_required(self):
        source = self.write(
            namespace="synthetic-import",
            external_id="a",
            payload=payload(),
            file_bytes=b"synthetic read-only example",
            filename="source.txt",
            media_type="text/plain",
        )
        with self.assertRaises(cases.CaseConflict):
            roundtrip.prepare(**self.common, selected=[roundtrip.pin(source)])
        approved_read_only = self.approve(source, uses=["READ"])
        with self.assertRaises(cases.CaseConflict):
            roundtrip.prepare(**self.common, selected=[roundtrip.pin(approved_read_only)])
        exportable = self.exportable("b")
        self.import_authority.denied.add("EXPORT")
        with self.assertRaises(cases.CaseConflict):
            roundtrip.prepare(**self.common, selected=[roundtrip.pin(exportable)])
        self.import_authority.denied.clear()
        self.authority.denied.add("EXPORT")
        with self.assertRaises(cases.CaseConflict):
            roundtrip.prepare(**self.common, selected=[roundtrip.pin(exportable)])
        self.assertEqual(RoundtripReceipt.objects.count(), 0)

    def test_revoked_grant_after_preview_closes_download_without_a_receipt(self):
        source = self.exportable()
        preview = roundtrip.prepare(**self.common, selected=[roundtrip.pin(source)])
        self.authority.denied.add(("EXPORT", source["digest"]))
        with self.assertRaises(cases.CaseConflict):
            roundtrip.download(
                **self.common,
                selected=preview["selected"],
                prepared_at=preview["prepared_at"],
                expected_sha256=preview["sha256"],
                request_key=uuid.uuid4(),
            )
        self.assertEqual(RoundtripReceipt.objects.count(), 0)

    def test_last_library_callback_cannot_revoke_already_checked_import_authority(self):
        source = self.exportable()
        preview = roundtrip.prepare(**self.common, selected=[roundtrip.pin(source)])
        actual = RoundtripReceipt.objects.create

        def late(**kwargs):
            row = actual(**kwargs)
            self.authority.hook = lambda _values: self.import_authority.denied.add("EXPORT")
            return row

        with (
            patch.object(RoundtripReceipt.objects, "create", side_effect=late),
            self.assertRaises(cases.CaseConflict),
        ):
            roundtrip.download(
                **self.common,
                selected=preview["selected"],
                prepared_at=preview["prepared_at"],
                expected_sha256=preview["sha256"],
                request_key=uuid.uuid4(),
            )
        self.authority.hook = None
        self.assertEqual(RoundtripReceipt.objects.count(), 0)

    def test_late_value_equal_authority_replacement_cannot_reuse_old_export_permission(self):
        class EqualAuthority(FixtureAuthority):
            def __eq__(self, other):
                return isinstance(other, EqualAuthority)

            def projection_epoch(self):
                # Revision namespaces are local to each independently configured
                # provider; equal tokens do not identify the same authority.
                return "revision-1"

        source = self.exportable()
        old = EqualAuthority(self.receipt["public_ref"])
        replacement = EqualAuthority(self.receipt["public_ref"])
        replacement.denied.add("EXPORT")
        actual = RoundtripReceipt.objects.create

        def create(**kwargs):
            row = actual(**kwargs)
            self.authority.hook = lambda _values: setattr(
                settings, "FATWA_MATERIAL_IMPORT_AUTHORITY", replacement
            )
            return row

        with override_settings(FATWA_MATERIAL_IMPORT_AUTHORITY=old):
            preview = roundtrip.prepare(**self.common, selected=[roundtrip.pin(source)])
            with (
                patch.object(RoundtripReceipt.objects, "create", side_effect=create),
                self.assertRaises(cases.CaseConflict),
            ):
                roundtrip.download(
                    **self.common,
                    selected=preview["selected"],
                    prepared_at=preview["prepared_at"],
                    expected_sha256=preview["sha256"],
                    request_key=uuid.uuid4(),
                )
        self.authority.hook = None
        self.assertEqual(RoundtripReceipt.objects.count(), 0)

    def test_oversized_aggregate_refuses_complete_package_instead_of_dropping_files(self):
        sources = [
            self.exportable(f"large-{number}", bytes([65 + number]) * 65536) for number in range(3)
        ]
        with self.assertRaisesRegex(cases.CaseConflict, "roundtrip_size_exceeded"):
            roundtrip.prepare(**self.common, selected=[roundtrip.pin(row) for row in sources])
        self.assertEqual(RoundtripReceipt.objects.count(), 0)

    def test_last_identity_callback_cannot_revoke_the_already_checked_import_grant(self):
        source = self.exportable()
        preview = roundtrip.prepare(**self.common, selected=[roundtrip.pin(source)])
        actual_create = RoundtripReceipt.objects.create
        actual_resolve = self.directory.resolve
        armed = False

        def create(**kwargs):
            nonlocal armed
            result = actual_create(**kwargs)
            armed = True
            return result

        def resolve(subject):
            result = actual_resolve(subject)
            if armed:
                self.import_authority.denied.add("EXPORT")
            return result

        with (
            patch.object(RoundtripReceipt.objects, "create", side_effect=create),
            patch.object(self.directory, "resolve", side_effect=resolve),
            self.assertRaises(cases.CaseConflict),
        ):
            roundtrip.download(
                **self.common,
                selected=preview["selected"],
                prepared_at=preview["prepared_at"],
                expected_sha256=preview["sha256"],
                request_key=uuid.uuid4(),
            )
        self.assertEqual(RoundtripReceipt.objects.count(), 0)

    def test_unversioned_identity_provider_cannot_export_or_render_saved_imports(self):
        source = self.exportable()
        with (
            patch.object(self.directory, "projection_epoch", None),
            self.assertRaises(cases.CaseConflict),
        ):
            roundtrip.prepare(**self.common, selected=[roundtrip.pin(source)])
        self.assertEqual(RoundtripReceipt.objects.count(), 0)

    def test_descriptive_source_exports_without_fabricating_file_and_receipt_is_immutable(self):
        source = self.approve(
            self.write(namespace="synthetic-import", external_id="description", payload=payload()),
            uses=["EXPORT"],
        )
        result, _ = self.export([source])
        parsed = formats.parse(result["raw"], result["filename"])
        self.assertEqual(parsed.files, {})
        self.assertEqual(parsed.rows[0]["file_member"], "")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoundtripReceipt.objects.all().update(artifact_sha256="a" * 64)
        changed = json.loads(json.dumps(parsed.origin))
        changed["namespace"] = "different"
        with self.assertRaises(formats.ImportInputError):
            services.stage(
                **self.common,
                raw=result["raw"],
                filename=result["filename"],
                namespace=changed["namespace"],
                provenance="اصطناعي",
                rights_basis="وصف فقط",
                request_key=uuid.uuid4(),
            )

    def test_sql_rejects_missing_json_contract_fields_in_plans_and_export_receipts(self):
        self.prepared()
        plan = ImportPlan.objects.get()
        for report in (
            {},
            {**plan.report, "ready": None},
            {**plan.report, "ready": False, "rows": [{"action": None}]},
        ):
            with (
                self.subTest(report=report),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                ImportPlan.objects.create(
                    batch=plan.batch,
                    mapping=plan.mapping,
                    number=2,
                    report=report,
                    digest="b" * 64,
                    case_revision=1,
                    evidence_version=1,
                    expires_at=plan.expires_at,
                    provider_id=plan.provider_id,
                    subject_id=plan.subject_id,
                    auth_epoch=plan.auth_epoch,
                )
        source = self.exportable()
        self.export([source])
        valid = RoundtripReceipt.objects.get()
        for scope, manifest in (
            ({}, {}),
            ({**valid.scope, "selected": None}, valid.manifest),
            (valid.scope, {**valid.manifest, "origin": {}}),
        ):
            with self.subTest(scope=scope), self.assertRaises(IntegrityError), transaction.atomic():
                RoundtripReceipt.objects.create(
                    case=valid.case,
                    provider_id=valid.provider_id,
                    subject_id=valid.subject_id,
                    auth_epoch=valid.auth_epoch,
                    request_key=uuid.uuid4(),
                    scope=scope,
                    scope_digest="a" * 64,
                    manifest=manifest,
                    artifact_sha256="b" * 64,
                    size=1,
                )


@override_settings(**FEATURES)
class RoundtripNativeTests(ImportFixture, TransactionTestCase):
    def source(self):
        return self.approve(
            self.write(
                namespace="synthetic-import",
                external_id="native-source",
                payload=payload(title="المادة المحددة وحدها"),
                file_bytes=b"native synthetic original\r\n",
                filename="original.txt",
                media_type="text/plain",
            ),
            uses=["EXPORT"],
        )

    def preview(self, client):
        fields = {"case_ref": self.receipt["public_ref"]}
        page = post(client, {**fields, "action": "mi_export_open"})
        self.assertEqual(page.status_code, 200)
        page = post(
            client,
            {
                **fields,
                "action": "mi_export_preview",
                "state": hidden(page, "state"),
                "selection": "0",
            },
            page,
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "معاينة الحزمة المحددة")
        return page

    def test_real_native_selection_preview_and_complete_manifested_download(self):
        source = self.source()
        client = self.login()
        page = self.preview(client)
        result = post(
            client,
            {
                "action": "mi_export",
                "case_ref": self.receipt["public_ref"],
                "state": hidden(page, "state"),
            },
            page,
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Content-Type"], "application/zip")
        self.assertIn("no-store", result["Cache-Control"])
        parsed = formats.parse(result.content, "materials.zip")
        self.assertEqual(parsed.origin["mapping"][0]["source_version_id"], source["version_id"])
        self.assertEqual(
            parsed.files[parsed.rows[0]["file_member"]].raw, b"native synthetic original\r\n"
        )
        self.assertEqual(
            RoundtripReceipt.objects.get().artifact_sha256, result["X-Material-Roundtrip-SHA256"]
        )

    def test_native_final_render_revocation_and_cross_browser_preview_refuse_bytes(self):
        self.source()
        client = self.login()
        preview = self.preview(client)
        stranger = self.login()
        result = post(
            stranger,
            {
                "action": "mi_export",
                "case_ref": self.receipt["public_ref"],
                "state": hidden(preview, "state"),
            },
        )
        self.assertEqual(result.status_code, 400)
        self.assertEqual(RoundtripReceipt.objects.count(), 0)
        from . import views

        actual = views.render

        def revoke(*args, **kwargs):
            result = actual(*args, **kwargs)
            if kwargs.get("context", {}) or len(args) > 2:
                self.authority.denied.add("EXPORT")
            return result

        with patch.object(views, "render", side_effect=revoke):
            page = post(
                client,
                {
                    "action": "mi_export_preview",
                    "case_ref": self.receipt["public_ref"],
                    "state": hidden(preview, "state"),
                    "selection": "0",
                },
                preview,
            )
        self.assertEqual(page.status_code, 409)
        self.assertNotContains(page, "المادة المحددة وحدها", status_code=409)
        self.assertEqual(RoundtripReceipt.objects.count(), 0)
