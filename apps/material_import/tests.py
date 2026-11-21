"""Actual canonical library writes, immutable PostgreSQL rows and current authority."""

import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, connections, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseEvent, CaseSource
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.fixtures import synthetic_files
from apps.research_library import services as library
from apps.research_library.models import LibraryBlob, LibraryDecision, LibraryItem, LibraryVersion
from apps.research_library.test_support import FEATURES as LIBRARY_FEATURES
from apps.research_library.test_support import LibraryFixture, payload
from tests.casework.test_http import hidden

from . import formats, services
from .authority import ImportAuthority
from .models import (
    GroupResult,
    ImportBatch,
    ImportDecision,
    ImportEvent,
    ImportPlan,
    MappingRevision,
)
from .test_formats import archive

FEATURES = {
    **LIBRARY_FEATURES,
    "FATWA_MATERIAL_IMPORT_ENABLED": True,
    "FATWA_MATERIAL_IMPORT_TTL_SECONDS": 1800,
    "ROOT_URLCONF": "config.campaign_urls",
}
URL = "/casework/staff/"


class FixtureAuthority(ImportAuthority):
    def __init__(self, ref):
        self.ref, self.denied, self.hook = ref, set(), None

    def projection_epoch(self):
        return repr((self.ref, sorted(self.denied)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["case_ref"] == self.ref
            and values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["action"]
            in {"VIEW", "STAGE", "MAP", "PLAN", "REVIEW", "APPLY", "CANCEL", "EXPORT"}
            and values["action"] not in self.denied
        )


def source_row(external_id="book-a", **changes):
    value = payload()
    value.pop("synthetic")
    return {"_synthetic": True, "external_id": external_id, **value, **changes}


def post(client, fields, page=None):
    token = (
        hidden(page, "csrfmiddlewaretoken")
        if page is not None
        else client.cookies["fatwa_casework_csrf"].value
    )
    return client.post(
        URL,
        urlencode({"csrfmiddlewaretoken": token, **fields}),
        content_type="application/x-www-form-urlencoded",
    )


class ImportFixture(LibraryFixture):
    def setUp(self):
        super().setUp()
        self.import_authority = FixtureAuthority(self.receipt["public_ref"])
        configured = override_settings(FATWA_MATERIAL_IMPORT_AUTHORITY=self.import_authority)
        configured.enable()
        self.addCleanup(configured.disable)

    def stage(self, rows=None, **changes):
        return services.stage(
            **self.common,
            raw=json.dumps(rows or [source_row()], ensure_ascii=False).encode(),
            filename=changes.pop("filename", "records.json"),
            namespace="synthetic-import",
            provenance="مولد محليًا للاختبار؛ لا مصدر حقيقي",
            rights_basis="بيانات تطوير اصطناعية لا تمنح إتاحة",
            request_key=uuid.uuid4(),
            expected_revision=1,
            expected_evidence_version=1,
            **changes,
        )

    def configure(self, batch, **changes):
        mapping = {key: key if key in batch["columns"] else "" for key in formats.FIELDS}
        return services.configure(
            **self.common,
            batch_id=batch["id"],
            mapping=changes.pop("mapping", mapping),
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
            **changes,
        )

    def plan(self, batch):
        return services.prepare_plan(
            **self.common,
            batch_id=batch["id"],
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )

    def prepared(self, rows=None):
        return self.plan(self.configure(self.stage(rows)))

    def review(self, batch, **changes):
        return services.decide(
            **{**self.common, "subject_id": changes.pop("subject_id", "other")},
            batch_id=batch["id"],
            plan_id=batch["plan"]["id"],
            verdict=changes.pop("verdict", "APPROVE"),
            note="راجعت القيم والنسخ والتعارضات",
            verification_note="تحققت من هوية المصدر الاصطناعي والبصمات؛ لا اعتماد علمي",
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
            **changes,
        )

    def apply(self, batch, **changes):
        return services.apply_batch(
            **self.common,
            batch_id=batch["id"],
            expected_sequence=batch["sequence"],
            request_key=changes.pop("request_key", uuid.uuid4()),
            **changes,
        )

    def login(self, subject="editor"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        credential = (
            "synthetic-editor-credential-32-characters"
            if subject == "editor"
            else "synthetic-reviewer-credential-32-characters"
        )
        response = client.post(
            "/casework/staff/login/",
            urlencode(
                {
                    "credential": credential,
                    "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                }
            ),
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 303)
        return client


@override_settings(**FEATURES)
class ImportTests(ImportFixture, TransactionTestCase):
    def test_file_group_holds_exact_external_binding_through_canonical_commit(self):
        observations = []

        class ObservedStorage(FileSystemStorage):
            @contextmanager
            def binding_lock(storage, digest):
                with super().binding_lock(digest):
                    depth = getattr(storage, "depth", 0)
                    storage.depth = depth + 1
                    try:
                        yield
                        if depth == 0:
                            observations.append(
                                (
                                    connection.in_atomic_block,
                                    LibraryBlob.objects.filter(pk=digest).exists(),
                                    GroupResult.objects.count(),
                                )
                            )
                    finally:
                        storage.depth = depth

        raw = "أصل اصطناعي محفوظ عبر معاملة مجموعة الإدخال\r\n".encode()
        packet = archive(
            [source_row(file_member="files/source.txt")],
            [("files/source.txt", "source.txt", "text/plain", raw)],
        )
        with tempfile.TemporaryDirectory(prefix="material-import-bindings-") as folder:
            storage = ObservedStorage(Path(folder) / "private", synthetic_fixtures_only=True)
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage):
                batch = services.stage(
                    **self.common,
                    raw=packet,
                    filename="source.zip",
                    namespace="synthetic-import",
                    provenance="مثال اصطناعي محفوظ",
                    rights_basis="بيانات تطوير اصطناعية",
                    request_key=uuid.uuid4(),
                )
                batch = self.apply(self.review(self.plan(self.configure(batch))))
                self.assertEqual(batch["state"], "APPLIED")
                self.assertEqual(observations, [(False, True, 1)])
                blob = LibraryBlob.objects.get()
                self.assertEqual((storage.root / "objects" / blob.storage_key).read_bytes(), raw)

    def test_durable_plan_independent_approval_canonical_apply_reconcile_and_idempotent_retry(self):
        original = "  أَصْلٌ اصطناعي\r\nلا يغيره الإدخال  "
        before = (
            list(CaseSource.objects.values()),
            list(AnswerRevision.objects.values()),
            list(CaseEvent.objects.values()),
        )
        batch = self.prepared([source_row(recorded_text=original)])
        self.assertEqual(batch["state"], "PLANNED")
        self.assertEqual(LibraryItem.objects.count(), 0)
        with self.assertRaisesRegex(cases.CaseConflict, "independent_reviewer"):
            self.review(batch, subject_id="editor")
        batch = self.review(batch)
        key = uuid.uuid4()
        applied = self.apply(batch, request_key=key)
        self.assertEqual((applied["state"], applied["completed_groups"]), ("APPLIED", 1))
        item = library.current_material(
            **self.common, namespace="synthetic-import", external_id="book-a"
        )
        self.assertEqual(item["payload"]["recorded_text"], original)
        self.assertEqual(item["state"], "DRAFT")
        self.assertEqual(LibraryDecision.objects.count(), 0)
        self.assertEqual(self.apply(batch, request_key=key)["state"], "APPLIED")
        self.assertEqual((LibraryVersion.objects.count(), GroupResult.objects.count()), (1, 1))
        self.assertEqual(
            before,
            (
                list(CaseSource.objects.values()),
                list(AnswerRevision.objects.values()),
                list(CaseEvent.objects.values()),
            ),
        )
        self.assertNotIn("history", GroupResult.objects.get().outcomes[0]["result"])

    def test_renamed_input_reuses_receipt_and_new_batch_identical_material_skips(self):
        rows = [source_row()]
        first = self.stage(rows)
        again = self.stage(rows, filename="renamed.json")
        self.assertEqual(first["id"], again["id"])
        done = self.apply(self.review(self.plan(self.configure(first))))
        raw = json.dumps(rows, ensure_ascii=False, indent=2).encode()
        second = services.stage(
            **self.common,
            raw=raw,
            filename="spaced.json",
            namespace="synthetic-import",
            provenance="مولد محليًا للاختبار؛ لا مصدر حقيقي",
            rights_basis="بيانات تطوير اصطناعية لا تمنح إتاحة",
            request_key=uuid.uuid4(),
        )
        second = self.plan(self.configure(second))
        self.assertEqual(second["plan"]["report"]["rows"][0]["reason"], "identical_material")
        self.assertEqual(self.apply(self.review(second))["state"], "APPLIED")
        self.assertEqual(LibraryVersion.objects.count(), 1)
        self.assertEqual(
            done["results"][0]["outcomes"][0]["result"]["version_id"],
            str(LibraryVersion.objects.get().pk),
        )

    def test_actual_zip_media_pin_storage_and_no_inherited_read_or_public_release(self):
        filename, media_type, raw = next(
            value for value in synthetic_files() if value[0].endswith(".wav")
        )
        rows = [source_row("audio-a", kind="AUDIO", file_member="files/clip.wav")]
        bundle = archive(rows, [("files/clip.wav", filename, media_type, raw)])
        batch = services.stage(
            **self.common,
            raw=bundle,
            filename="bundle.zip",
            namespace="synthetic-import",
            provenance="صوت اصطناعي مولد للاختبار",
            rights_basis="لا ترخيص خارجي",
            request_key=uuid.uuid4(),
        )
        applied = self.apply(self.review(self.plan(self.configure(batch))))
        self.assertEqual(applied["state"], "APPLIED")
        version = LibraryVersion.objects.select_related("blob").get()
        self.assertEqual(bytes(version.blob.original), raw)
        self.assertEqual(version.blob.sha256, sha256(raw).hexdigest())
        with self.assertRaises(cases.CaseConflict):
            library.file_content(**self.common, version_id=version.pk, usage="READ")
        self.assertEqual(LibraryDecision.objects.count(), 0)

    def test_validation_distinguishes_missing_optional_text_duplicate_rows_and_bad_file(self):
        good = self.prepared([source_row(recorded_text="")])
        self.assertTrue(good["plan"]["report"]["ready"])
        bad = self.prepared([source_row("duplicate"), source_row("duplicate", title="عنوان آخر")])
        self.assertEqual(bad["state"], "BLOCKED")
        self.assertEqual(
            {row["reason"] for row in bad["plan"]["report"]["rows"]}, {"duplicate_external_id"}
        )
        with self.assertRaises(cases.CaseConflict):
            self.review(bad)
        invalid = self.prepared([source_row("missing", file_member="files/absent.pdf")])
        self.assertEqual(invalid["plan"]["report"]["rows"][0]["reason"], "referenced_file_missing")
        self.assertEqual(LibraryItem.objects.count(), 0)

    def test_human_conflict_requires_exact_resolution_keeps_prior_version_and_blank_values(self):
        old = self.write(
            namespace="synthetic-import",
            external_id="book-a",
            payload=payload(description="تحرير بشري محفوظ"),
        )
        batch = self.prepared([source_row(title="عنوان مصدر جديد", description="")])
        row = batch["plan"]["report"]["rows"][0]
        self.assertEqual((batch["state"], row["reason"]), ("BLOCKED", "human_conflict"))
        self.assertEqual(row["payload"]["description"], "تحرير بشري محفوظ")
        resolved = services.resolve_conflict(
            **self.common,
            batch_id=batch["id"],
            external_id="book-a",
            choice="NEW_VERSION",
            expected_target=row["target"],
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )
        applied = self.apply(self.review(self.plan(resolved)))
        self.assertEqual(applied["state"], "APPLIED")
        current = library.current_material(
            **self.common, namespace="synthetic-import", external_id="book-a"
        )
        self.assertEqual(
            (current["number"], current["payload"]["description"]), (2, "تحرير بشري محفوظ")
        )
        self.assertEqual(
            LibraryVersion.objects.get(pk=old["version_id"]).payload["title"],
            old["payload"]["title"],
        )

    def test_live_human_edit_after_approval_never_overwritten_and_stale_values_not_projected(self):
        batch = self.review(self.prepared())
        self.write(
            namespace="synthetic-import",
            external_id="book-a",
            payload=payload(title="عنوان بشري أحدث"),
        )
        with self.assertRaisesRegex(cases.CaseConflict, "target_changed"):
            self.apply(batch)
        status = services.read_batch(**self.common, batch_id=batch["id"])
        self.assertEqual(status["state"], "STALE")
        self.assertIsNone(status["plan"]["report"])
        self.assertEqual(LibraryVersion.objects.count(), 1)
        self.assertEqual(GroupResult.objects.count(), 0)

    def test_mapping_change_invalidates_old_decision_and_stale_version_resolution(self):
        batch = self.review(self.prepared())
        revised = self.configure(batch)
        with self.assertRaisesRegex(cases.CaseConflict, "plan_stale"):
            self.apply(revised)
        refreshed = self.plan(revised)
        self.assertEqual(refreshed["state"], "PLANNED")
        self.assertIsNone(refreshed["decision"])
        self.assertEqual(ImportDecision.objects.count(), 1)

    def test_dependency_group_rolls_back_and_retry_preserves_completed_other_group(self):
        rows = [
            source_row("done", group="first"),
            source_row("a", group="second"),
            source_row("b", group="second"),
        ]
        batch = self.review(self.prepared(rows))
        actual = library.write_material

        def fail_second(**kwargs):
            if kwargs["external_id"] == "b":
                raise cases.CaseConflict("simulated_storage_failure")
            return actual(**kwargs)

        with patch.object(library, "write_material", side_effect=fail_second):
            partial = self.apply(batch)
        self.assertEqual((partial["state"], partial["completed_groups"]), ("PARTIAL", 1))
        self.assertEqual(list(LibraryItem.objects.values_list("external_id", flat=True)), ["done"])
        self.assertEqual(GroupResult.objects.count(), 1)
        finished = self.apply(partial)
        self.assertEqual(
            (finished["state"], LibraryItem.objects.count(), GroupResult.objects.count()),
            ("APPLIED", 3, 2),
        )

    def test_cancel_keeps_original_and_successful_groups_and_cannot_resume(self):
        batch = self.review(self.prepared())
        cancelled = services.cancel(
            **self.common,
            batch_id=batch["id"],
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )
        self.assertEqual(cancelled["state"], "CANCELLED")
        with self.assertRaises(cases.CaseConflict):
            self.apply(cancelled)
        self.assertEqual(
            (
                ImportBatch.objects.count(),
                ImportPlan.objects.count(),
                LibraryVersion.objects.count(),
            ),
            (1, 1, 0),
        )

    def test_late_import_revocation_rolls_back_actual_canonical_write_and_receipt(self):
        batch = self.review(self.prepared())
        actual = library.write_material

        def revoke(**kwargs):
            result = actual(**kwargs)
            self.import_authority.denied.add("APPLY")
            return result

        with (
            patch.object(library, "write_material", side_effect=revoke),
            self.assertRaises(cases.CaseConflict),
        ):
            self.apply(batch)
        self.assertEqual(
            (
                LibraryItem.objects.count(),
                LibraryVersion.objects.count(),
                GroupResult.objects.count(),
            ),
            (0, 0, 0),
        )

    def test_final_library_callback_cannot_commit_an_unselected_hidden_material(self):
        batch = self.review(self.prepared())
        actual = library.write_material
        fired = False

        def extra(**kwargs):
            nonlocal fired
            result = actual(**kwargs)
            if not fired:
                fired = True
                actual(
                    **self.common,
                    namespace="synthetic-import",
                    external_id="hidden-extra",
                    payload=payload(),
                    expected_version=0,
                    request_key=uuid.uuid4(),
                    expected_revision=1,
                    expected_evidence_version=1,
                )
            return result

        with patch.object(library, "write_material", side_effect=extra):
            result = self.apply(batch)
        self.assertTrue(fired)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual((LibraryItem.objects.count(), GroupResult.objects.count()), (0, 0))

    def test_expired_batch_remains_readable_but_cannot_apply(self):
        batch = self.review(self.prepared())
        future = ImportBatch.objects.get().expires_at + timedelta(seconds=1)
        self.directory.identities = {
            key: replace(value, valid_until=future + timedelta(minutes=10))
            for key, value in self.directory.identities.items()
        }
        with patch("apps.material_import.services.timezone.now", return_value=future):
            self.assertEqual(
                services.read_batch(**self.common, batch_id=batch["id"])["state"], "EXPIRED"
            )
            with self.assertRaises(cases.CaseConflict):
                self.apply(batch)
        self.assertEqual(LibraryVersion.objects.count(), 0)

    def test_parallel_receipt_and_stale_plans_do_not_duplicate_rows(self):
        def run():
            connections.close_all()
            try:
                return self.stage()["id"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            identities = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(identities[0], identities[1])
        batch = self.configure(services.read_batch(**self.common, batch_id=identities[0]))
        first = self.plan(batch)
        with self.assertRaisesRegex(cases.CaseConflict, "stale_command"):
            self.plan(batch)
        self.assertEqual((ImportBatch.objects.count(), ImportPlan.objects.count()), (1, 1))
        self.assertEqual(first["state"], "PLANNED")

    def test_sql_immutability_self_review_and_cross_batch_mapping_are_real_constraints(self):
        self.prepared()
        for model in (ImportBatch, MappingRevision, ImportPlan, ImportEvent):
            with (
                self.subTest(model=model.__name__),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                model.objects.all().delete()
        plan = ImportPlan.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ImportDecision.objects.create(
                plan=plan,
                verdict="APPROVE",
                note="note",
                verification_note="checked",
                subject_id=plan.subject_id,
                provider_id=plan.provider_id,
                auth_epoch=plan.auth_epoch,
            )
        second = self.configure(self.stage([source_row("another")]))
        other_mapping = MappingRevision.objects.get(batch_id=second["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ImportPlan.objects.create(
                batch=plan.batch,
                mapping=other_mapping,
                number=2,
                report=plan.report,
                digest="a" * 64,
                case_revision=1,
                evidence_version=1,
                expires_at=plan.expires_at,
                subject_id="editor",
                provider_id=plan.provider_id,
                auth_epoch=plan.auth_epoch,
            )
        self.assertEqual(ImportDecision.objects.count(), 0)

    def test_same_case_scope_and_two_independent_policies_remain_mandatory(self):
        batch = self.prepared()
        with (
            override_settings(FATWA_MATERIAL_IMPORT_AUTHORITY=None),
            self.assertRaises(cases.CaseConflict),
        ):
            services.read_batch(**self.common, batch_id=batch["id"])
        self.authority.denied.add("VIEW")
        with self.assertRaises(cases.CaseConflict):
            services.read_batch(**self.common, batch_id=batch["id"])
        self.authority.denied.clear()
        foreign = cases.intake_case(
            original_question="قضية أخرى اصطناعية",
            source_event_id=uuid.uuid4().hex,
            requester_id="another",
            idempotency_key=uuid.uuid4().hex,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            services.read_batch(
                **{**self.common, "case_id": foreign["case_id"]}, batch_id=batch["id"]
            )
        self.assertEqual(LibraryItem.objects.count(), 0)


@override_settings(**FEATURES)
class ImportNativeTests(ImportFixture, TransactionTestCase):
    def upload(self, client, page, rows):
        return client.post(
            URL,
            {
                "action": "mi_upload",
                "case_ref": self.receipt["public_ref"],
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "state": hidden(page, "state"),
                "namespace": "synthetic-import",
                "provenance": "مصدر اصطناعي موثق للاختبار",
                "rights_basis": "مثال مولد؛ لا ترخيص خارجي",
                "synthetic": "yes",
                "source_file": SimpleUploadedFile(
                    "records.json",
                    json.dumps(rows, ensure_ascii=False).encode(),
                    content_type="application/json",
                ),
            },
        )

    def test_actual_native_upload_map_plan_other_reviewer_apply_and_open_canonical_reader(self):
        client = self.login()
        page = post(client, {"action": "mi_open", "case_ref": self.receipt["public_ref"]})
        self.assertEqual(page.status_code, 200)
        page = self.upload(client, page, [source_row()])
        self.assertEqual(page.status_code, 200)
        batch = ImportBatch.objects.get()
        common = {"case_ref": self.receipt["public_ref"], "batch_id": str(batch.pk)}
        mapping = {key: key if key in source_row() else "" for key in formats.FIELDS}
        page = post(
            client,
            {
                **common,
                "action": "mi_map",
                "state": hidden(page, "state"),
                **{"map_" + key: value for key, value in mapping.items()},
            },
            page,
        )
        self.assertEqual(page.status_code, 200)
        page = post(client, {**common, "action": "mi_plan", "state": hidden(page, "state")}, page)
        self.assertEqual(page.status_code, 200)
        reviewer = self.login("other")
        reviewed = post(reviewer, {**common, "action": "mi_batch"})
        reviewed = post(
            reviewer,
            {
                **common,
                "action": "mi_approve",
                "state": hidden(reviewed, "state"),
                "plan_id": str(ImportPlan.objects.get().pk),
                "note": "راجعت البيانات",
                "verification_note": "تحققت من أصل المثال الاصطناعي",
            },
            reviewed,
        )
        self.assertEqual(reviewed.status_code, 200)
        page = post(client, {**common, "action": "mi_batch"})
        page = post(client, {**common, "action": "mi_apply", "state": hidden(page, "state")}, page)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "اكتمل النطاق المعتمد")
        self.assertEqual(LibraryVersion.objects.count(), 1)
        opened = post(
            client,
            {
                "action": "rl_item",
                "case_ref": self.receipt["public_ref"],
                "version_id": str(LibraryVersion.objects.get().pk),
            },
        )
        self.assertEqual(opened.status_code, 200)
        self.assertContains(opened, source_row()["title"])
        self.assertIn("no-store", page["Cache-Control"])
        self.assertEqual(LibraryDecision.objects.count(), 0)

    def test_real_csrf_foreign_browser_state_cross_case_and_render_revocation(self):
        client = self.login()
        page = post(client, {"action": "mi_open", "case_ref": self.receipt["public_ref"]})
        self.assertEqual(
            client.post(
                URL,
                urlencode({"action": "mi_open", "case_ref": self.receipt["public_ref"]}),
                content_type="application/x-www-form-urlencoded",
            ).status_code,
            403,
        )
        other_browser = self.login()
        wrong = self.upload(other_browser, page, [source_row()])
        self.assertIn(wrong.status_code, (400, 403))
        self.assertEqual(ImportBatch.objects.count(), 0)
        from . import views

        actual = views.render

        def revoke(*args, **kwargs):
            response = actual(*args, **kwargs)
            self.import_authority.denied.add("VIEW")
            return response

        with patch.object(views, "render", side_effect=revoke):
            response = post(client, {"action": "mi_open", "case_ref": self.receipt["public_ref"]})
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, "مركز إدخال", status_code=409)

    def test_render_cancellation_remapping_and_empty_inbox_insertion_cannot_publish_old_html(self):
        from . import views

        client = self.login()
        actual = views.render
        with patch.object(
            views,
            "render",
            side_effect=lambda *args, **kwargs: (actual(*args, **kwargs), self.stage())[0],
        ):
            response = post(client, {"action": "mi_open", "case_ref": self.receipt["public_ref"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ImportBatch.objects.count(), 0)
        batch = self.review(self.prepared())
        sequence = ImportEvent.objects.count()
        for command in ("cancel", "remap"):

            def mutate(*args, **kwargs):
                response = actual(*args, **kwargs)
                if command == "cancel":
                    services.cancel(
                        **self.common,
                        batch_id=batch["id"],
                        expected_sequence=batch["sequence"],
                        request_key=uuid.uuid4(),
                    )
                else:
                    self.configure(batch)
                return response

            with self.subTest(command=command), patch.object(views, "render", side_effect=mutate):
                response = post(
                    client,
                    {
                        "action": "mi_batch",
                        "case_ref": self.receipt["public_ref"],
                        "batch_id": batch["id"],
                    },
                )
            self.assertEqual(response.status_code, 409)
            self.assertNotContains(response, "import-apply-form", status_code=409)
            self.assertEqual(ImportEvent.objects.count(), sequence)
            self.assertEqual(
                services.read_batch(**self.common, batch_id=batch["id"])["state"], "APPROVED"
            )

    def test_single_native_upload_rolls_back_when_its_render_loses_current_access(self):
        from . import views

        client = self.login()
        page = post(client, {"action": "mi_open", "case_ref": self.receipt["public_ref"]})
        actual = views.render

        def revoke(*args, **kwargs):
            response = actual(*args, **kwargs)
            self.import_authority.denied.add("VIEW")
            return response

        with patch.object(views, "render", side_effect=revoke):
            response = self.upload(client, page, [source_row()])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ImportBatch.objects.count(), 0)
        self.assertEqual(ImportEvent.objects.count(), 0)
