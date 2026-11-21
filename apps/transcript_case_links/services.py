"""Reuse case lock/identity/history contracts; never import source answers as rulings."""

import uuid
from hashlib import sha256

from apps.casework import services as cases
from apps.casework.models import CaseEvidence
from apps.fast8_transcript_queue.workbench.services import restore_bundle, review
from apps.platform_recovery.integration import mutation_service
from apps.upload_security import integration as scans
from apps.upload_security import services as scan_receipts

from .models import TranscriptLink, TranscriptUpload

MAX_BUNDLE = 192_000  # Compatible with the unchanged shared 256 KiB request guard.


def _entries(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BUNDLE:
        raise cases.CaseConflict("transcript_bundle_size")
    try:
        scans.require_bytes(raw)
        if scans.active([raw]):
            from apps.fast8_transcript_queue.workbench.services import _read_archive

            for member in _read_archive(raw).values():
                scans.require_bytes(member)
        document = restore_bundle(raw, synthetic_fixtures_only=True)
        _, _, queue, error = review(document)
        if queue is None or error:
            raise ValueError("unfinished")
        for entry in queue.entries:
            cases._text(entry.question.text)
        return queue.entries
    except ValueError as exc:
        raise cases.CaseConflict("reviewed_transcript_required") from exc


def _summary(case, upload, entries):
    return {
        "public_ref": case.public_ref,
        "case_id": str(case.pk),
        "upload_id": str(upload.pk),
        "bundle_sha256": upload.sha256,
        "revision": upload.case_revision,
        "evidence_version": upload.evidence_version,
        "entries": entries,
    }


@mutation_service
def preview(*, case_id, subject_id, provider, bundle, synthetic_fixtures_only=False):
    scans.transcript_bundle(
        raw=bundle,
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    with (
        scan_receipts.boundary(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
    ):
        entries = _entries(bundle)
        existing = TranscriptUpload.objects.filter(
            case=case,
            sha256=sha256(bundle).hexdigest(),
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
            case_revision=case.revision,
            evidence_version=case.evidence_version,
        ).first()
        if existing:
            return _summary(case, existing, entries)
        if TranscriptUpload.objects.filter(case=case).count() >= 32:
            raise cases.CaseConflict("transcript_upload_capacity")
        upload = TranscriptUpload.objects.create(
            case=case,
            bundle=bundle,
            sha256=sha256(bundle).hexdigest(),
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
            case_revision=case.revision,
            evidence_version=case.evidence_version,
        )
        return _summary(case, upload, entries)


def _upload(case, actor, provider, upload_id):
    upload = TranscriptUpload.objects.filter(
        pk=cases._uuid(upload_id),
        case=case,
        subject_id=actor.subject_id,
        provider_id=provider.provider_id,
        auth_epoch=actor.auth_epoch,
    ).first()
    if upload is None or sha256(bytes(upload.bundle)).hexdigest() != upload.sha256:
        raise cases.CaseConflict("transcript_upload_unavailable")
    scans.require_bytes(bytes(upload.bundle))
    return upload


@mutation_service
def attach(*, case_id, subject_id, provider, upload_id, external_id, synthetic_fixtures_only=False):
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        upload = _upload(case, actor, provider, upload_id)
        entry = next(
            (e for e in _entries(bytes(upload.bundle)) if e.external_id == external_id), None
        )
        if entry is None:
            raise cases.CaseConflict("transcript_question_unavailable")
        existing = (
            TranscriptLink.objects.select_related("upload", "evidence", "event")
            .filter(case=case, external_id=external_id)
            .first()
        )
        if existing:
            if existing.upload.sha256 != upload.sha256:
                raise cases.CaseConflict("transcript_provenance_conflict")
            _check_link(existing, entry)
            return {
                "created": False,
                "link_id": str(existing.pk),
                "version": existing.evidence.version,
            }
        cases._versions(case, upload.case_revision, upload.evidence_version)
        if case.stage == "NEEDS_CLARIFICATION":
            raise cases.CaseConflict("requester_clarification_still_required")
        link_id = uuid.uuid4()
        case.evidence_version += 1
        evidence = CaseEvidence.objects.create(
            case=case,
            version=case.evidence_version,
            kind="FOLLOWUP",
            text=entry.question.text,
            text_sha256=cases._digest(entry.question.text),
        )
        case.stage, case.approved_answer = "UNDER_REVIEW", None
        cases._event(case, "FOLLOWUP", actor.subject_id, note="TRANSCRIPT:" + str(link_id))
        link = TranscriptLink.objects.create(
            id=link_id,
            case=case,
            upload=upload,
            evidence=evidence,
            event=case.events.get(sequence=case.revision),
            external_id=external_id,
            question_sha256=evidence.text_sha256,
        )
        return {"created": True, "link_id": str(link.pk), "version": evidence.version}


def _check_link(link, entry):
    if (
        link.evidence.case_id != link.case_id
        or link.event.case_id != link.case_id
        or link.upload.case_id != link.case_id
        or link.event.action != "FOLLOWUP"
        or link.event.note != "TRANSCRIPT:" + str(link.pk)
        or link.event.subject_id != link.upload.subject_id
        or link.event.evidence_version != link.evidence.version
        or entry.question.text != link.evidence.text
        or cases._digest(entry.question.text) != link.question_sha256
    ):
        raise cases.CaseConflict("transcript_binding_inconsistent")


@mutation_service
def read_links(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        result = []
        for link in (
            TranscriptLink.objects.filter(case=case)
            .select_related("upload", "evidence", "event")
            .order_by("evidence__version")
        ):
            from apps.data_privacy.integration import allowed as privacy_allowed

            if not privacy_allowed("TRANSCRIPT_LINK", link.pk):
                continue
            raw = bytes(link.upload.bundle)
            if sha256(raw).hexdigest() != link.upload.sha256:
                raise cases.CaseConflict("transcript_binding_inconsistent")
            entry = next((e for e in _entries(raw) if e.external_id == link.external_id), None)
            if entry is None:
                raise cases.CaseConflict("transcript_binding_inconsistent")
            _check_link(link, entry)
            result.append(
                {
                    "id": str(link.pk),
                    "version": link.evidence.version,
                    "entry": entry,
                    "bundle_sha256": link.upload.sha256,
                    "actor": link.upload.subject_id,
                }
            )
        return result
