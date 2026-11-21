"""Nonempty real-service seed and fresh-process readers under synthetic policies only."""

import uuid
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.test import override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.research_library import services as library
from apps.research_library.test_support import FixtureAuthority as LibraryAuthority

from . import formats, roundtrip, services
from .models import (
    GroupResult,
    ImportBatch,
    ImportDecision,
    ImportEvent,
    ImportPlan,
    MappingRevision,
    RoundtripReceipt,
)
from .test_formats import archive
from .tests import FixtureAuthority, source_row

TABLES = (
    "material_import_importbatch",
    "material_import_mappingrevision",
    "material_import_importplan",
    "material_import_importdecision",
    "material_import_groupresult",
    "material_import_importevent",
    "material_import_roundtripreceipt",
)
TRIGGERS = tuple(
    "mi_" + table.removeprefix("material_import_") + suffix
    for table in TABLES
    for suffix in ("_insert", "_immutable")
)


def _configuration(pins):
    from apps.research_library.test_support import bind_identity_snapshot

    directory = Directory([pins["public_ref"]])
    bind_identity_snapshot(directory)
    common = dict(
        case_id=pins["case_id"],
        subject_id="editor",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    config = override_settings(
        FATWA_RESEARCH_LIBRARY_ENABLED=True,
        FATWA_MATERIAL_IMPORT_ENABLED=True,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_RESEARCH_LIBRARY_AUTHORITY=LibraryAuthority(pins["public_ref"]),
        FATWA_MATERIAL_IMPORT_AUTHORITY=FixtureAuthority(pins["public_ref"]),
        FATWA_MATERIAL_IMPORT_TTL_SECONDS=3600,
    )
    return common, config


def populate():
    key = "material-import-recovery-" + uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="قضية استعادة اصطناعية مستقلة عن مواد المكتبة",
        source_event_id=key,
        requester_id=key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    pins = {name: str(receipt[name]) for name in ("case_id", "public_ref")}
    raw = "أصل اصطناعي للاستعادة\r\nمحفوظ حرفيًا".encode()
    source = archive(
        [source_row("recovery-source", file_member="files/source.txt")],
        [("files/source.txt", "source.txt", "text/plain", raw)],
    )
    common, configuration = _configuration(pins)
    with configuration:
        batch = services.stage(
            **common,
            raw=source,
            filename="recovery.zip",
            namespace="synthetic-import-recovery",
            provenance="مولد محليًا لاختبار الاستعادة",
            rights_basis="مادة اصطناعية، لا ترخيص خارجي",
            request_key=uuid.uuid4(),
            expected_revision=1,
            expected_evidence_version=1,
        )
        batch = services.configure(
            **common,
            batch_id=batch["id"],
            mapping=formats.default_mapping(formats.parse(source, "recovery.zip")),
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
            note="مراجعة مستقلة للمثال الاصطناعي",
            verification_note="فحص المصدر والربط والبصمات",
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )
        batch = services.apply_batch(
            **common,
            batch_id=batch["id"],
            expected_sequence=batch["sequence"],
            request_key=uuid.uuid4(),
        )
        assert batch["state"] == "APPLIED"
        target = library.current_material(
            **common, namespace="synthetic-import-recovery", external_id="recovery-source"
        )
        reviewed = library.decide(
            **{**common, "subject_id": "other"},
            version_id=target["version_id"],
            action="REVIEW",
            note="فحص مستقل للمثال الاصطناعي",
            expected_actions=0,
            request_key=uuid.uuid4(),
            confirmed=True,
            expected_revision=1,
            expected_evidence_version=1,
        )
        library.decide(
            **{**common, "subject_id": "publisher"},
            version_id=target["version_id"],
            action="APPROVE",
            note="إتاحة تصدير اصطناعية محددة فقط",
            expected_actions=reviewed["action_count"],
            request_key=uuid.uuid4(),
            confirmed=True,
            uses=["EXPORT"],
            minutes=60,
            expected_revision=1,
            expected_evidence_version=1,
        )
        transfer = roundtrip.prepare(**common, selected=[roundtrip.pin(target)])
        packet = roundtrip.download(
            **common,
            selected=transfer["selected"],
            prepared_at=transfer["prepared_at"],
            expected_sha256=transfer["sha256"],
            request_key=uuid.uuid4(),
        )
        pins.update(
            batch_id=batch["id"],
            plan_digest=batch["plan"]["digest"],
            version_id=target["version_id"],
            version_digest=target["digest"],
            file_sha256=sha256(raw).hexdigest(),
            raw_sha256=sha256(source).hexdigest(),
            transfer_sha256=packet["sha256"],
        )
        assert all(
            model.objects.exists()
            for model in (
                ImportBatch,
                MappingRevision,
                ImportPlan,
                ImportDecision,
                GroupResult,
                ImportEvent,
                RoundtripReceipt,
            )
        )
    return pins


def verify_restored(pins):
    common, configuration = _configuration(pins)
    with configuration:
        batch = services.read_batch(**common, batch_id=pins["batch_id"])
        assert batch["state"] in {"APPLIED", "EXPIRED"}
        assert batch["completed_groups"] == batch["total_groups"] == 1
        assert batch["raw_sha256"] == pins["raw_sha256"]
        assert batch["plan"]["digest"] == pins["plan_digest"]
        target = library.current_material(
            **common, namespace="synthetic-import-recovery", external_id="recovery-source"
        )
        assert (target["version_id"], target["digest"], target["file"]["sha256"]) == (
            pins["version_id"],
            pins["version_digest"],
            pins["file_sha256"],
        )
        assert target["state"] == "APPROVE" and target["action_count"] == 2
        receipt = RoundtripReceipt.objects.get(case_id=pins["case_id"])
        assert receipt.artifact_sha256 == pins["transfer_sha256"]
        assert receipt.scope_digest == formats.digest(receipt.scope)
        for model in (
            ImportBatch,
            MappingRevision,
            ImportPlan,
            ImportDecision,
            GroupResult,
            ImportEvent,
            RoundtripReceipt,
        ):
            try:
                with transaction.atomic():
                    # A field shared by all seven models; history cannot be rewritten.
                    model.objects.all().update(subject_id="tampered-after-restore")
                raise AssertionError("Restored import history accepted mutation")
            except IntegrityError:
                pass
        with override_settings(FATWA_MATERIAL_IMPORT_AUTHORITY=None):
            try:
                services.read_batch(**common, batch_id=pins["batch_id"])
                raise AssertionError("Restore fabricated an import grant")
            except cases.CaseConflict:
                pass
        common["provider"].identities.pop("editor")
        try:
            services.read_batch(**common, batch_id=pins["batch_id"])
            raise AssertionError("Restore fabricated current identity")
        except cases.CaseConflict:
            pass
    return {
        "tables": TABLES,
        "raw_sha256": pins["raw_sha256"],
        "canonical_version": pins["version_id"],
        "current_authority_required": True,
        "scientific_approval_created": False,
    }
