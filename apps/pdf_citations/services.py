"""Human PDF page locators over exact canonical originals, never a media store."""

import os

from django.conf import settings
from django.db import connection

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service
from apps.private_media.validation import MediaValidationError, validate
from apps.source_rights.services import projection_expiry_guard
from apps.timed_citations.services import _current, _digest, _draft, _identity, _rights, _state

from .models import PdfCitation, PdfCitationAction


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PDF_CITATIONS_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("pdf_citations_disabled")


# Shared identity, explicit media READ/CITE and deadline checks, never a new rights store.


def _source(case, actor, provider, kind, identifier):
    identifier = cases._uuid(identifier)
    if kind == "ATTACHMENT":
        attachments._enabled()
        owner = (
            CaseAttachment.objects.filter(
                pk=identifier, case=case, kind="pdf", media_type="application/pdf"
            )
            .select_related("evidence", "event")
            .first()
        )
        if owner is None:
            raise cases.CaseConflict("pdf_source_unavailable")
        version, recorded = owner.evidence.version, owner.validation_metadata
    elif kind == "ANSWER_MEDIA":
        media._enabled()
        owner = (
            AnswerPart.objects.filter(
                pk=identifier,
                manifest__answer__case=case,
                kind="FILE",
                media_type="application/pdf",
            )
            .select_related("manifest__answer")
            .first()
        )
        if owner is None:
            raise cases.CaseConflict("pdf_source_unavailable")
        version, recorded = owner.manifest.answer.revision, owner.metadata
    else:
        raise cases.CaseConflict("pdf_source_kind_invalid")
    pin = {"kind": kind, "id": str(owner.pk), "sha256": owner.sha256}
    _rights(case, actor, provider, pin)
    if kind == "ATTACHMENT":
        raw = attachments._check(owner)
    else:
        cases._answer_citations(owner.manifest.answer)
        media._verified(owner.manifest)
        raw = media.raw_for_part(owner)
    try:
        verified = validate(raw, owner.filename, owner.media_type)
        pages = verified.metadata["pages"]
        if (
            verified.kind != "pdf"
            or verified.sha256 != owner.sha256
            or verified.metadata != recorded
            or type(pages) is not int
            or not 1 <= pages <= 10
            or verified.metadata.get("active_content") is not False
        ):
            raise ValueError
    except (MediaValidationError, KeyError, ValueError) as exc:
        raise cases.CaseConflict("pdf_pages_unverified") from exc
    pin.update(
        version=version,
        page_count=pages,
        metadata_sha256=_digest(recorded),
        filename=owner.filename,
        media_type=owner.media_type,
        size=owner.size,
    )
    _rights(case, actor, provider, pin)
    _identity(case, actor, provider)
    return pin, owner, raw


def _latest(row):
    if PdfCitation.objects.filter(series=row.series, number__gt=row.number).exists():
        raise cases.CaseConflict("pdf_revision_superseded")


def _validate(row, case, actor, provider):
    if row.snapshot_sha256 != _digest(row.snapshot) or row.page_count != row.snapshot.get(
        "page_count"
    ):
        raise cases.CaseConflict("pdf_snapshot_changed")
    pin, owner, raw = _source(case, actor, provider, row.snapshot["kind"], row.snapshot["id"])
    if pin != row.snapshot or str(owner.pk) != str(row.attachment_id or row.part_id):
        raise cases.CaseConflict("pdf_source_changed")
    return raw


@mutation_service
def inspect_source(
    *, case_id, subject_id, provider, kind, source_id, synthetic_fixtures_only=False
):
    _enabled()
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        return _source(case, actor, provider, kind, source_id)[0]


@mutation_service
def propose(
    *,
    case_id,
    subject_id,
    provider,
    source_pin,
    page_number,
    reason,
    expected_revision,
    expected_evidence_version,
    replaces_id=None,
    printed_label="",
    printed_confirmed=False,
    synthetic_fixtures_only=False,
):
    _enabled()
    cases._mutation_versions(expected_revision, expected_evidence_version)
    cases._text(reason)
    if len(reason) > 1000 or type(page_number) is not int:
        raise cases.CaseConflict("pdf_page_invalid")
    cases._text(printed_label, optional=True)
    if (
        len(printed_label) > 40
        or any(ord(c) < 32 or ord(c) == 127 for c in printed_label)
        or printed_label != printed_label.strip()
        or type(printed_confirmed) is not bool
        or bool(printed_label) != printed_confirmed
    ):
        raise cases.CaseConflict("pdf_explicit_printed_mapping_required")
    if type(source_pin) is not dict or set(source_pin) != {
        "kind",
        "id",
        "sha256",
        "version",
        "page_count",
        "metadata_sha256",
        "filename",
        "media_type",
        "size",
    }:
        raise cases.CaseConflict("pdf_exact_source_pin_required")
    if any(type(source_pin[key]) is not int for key in ("version", "page_count", "size")):
        raise cases.CaseConflict("pdf_exact_source_pin_required")
    with (
        cases._staff_case(
            case_id,
            subject_id,
            provider,
            synthetic_fixtures_only,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        ) as (case, actor),
        projection_expiry_guard(),
    ):
        answer = _draft(case)
        pin, owner, _ = _source(case, actor, provider, source_pin["kind"], source_pin["id"])
        if source_pin != pin:
            raise cases.CaseConflict("pdf_source_changed")
        if not 1 <= page_number <= pin["page_count"]:
            raise cases.CaseConflict("pdf_page_invalid")
        previous = None
        if replaces_id is not None:
            previous = PdfCitation.objects.filter(pk=cases._uuid(replaces_id), case=case).first()
            if previous is None:
                raise cases.CaseConflict("pdf_citation_unavailable")
            _latest(previous)
            if previous.number >= 64:
                raise cases.CaseConflict("pdf_capacity")
        elif PdfCitation.objects.filter(case=case, number=1).count() >= 32:
            raise cases.CaseConflict("pdf_capacity")
        _rights(case, actor, provider, pin)
        _identity(case, actor, provider)
        row = PdfCitation.objects.create(
            case=case,
            answer=answer,
            attachment=owner if pin["kind"] == "ATTACHMENT" else None,
            part=owner if pin["kind"] == "ANSWER_MEDIA" else None,
            previous=previous,
            number=previous.number + 1 if previous else 1,
            **({"series": previous.series} if previous else {}),
            snapshot=pin,
            snapshot_sha256=_digest(pin),
            page_number=page_number,
            printed_label=printed_label,
            printed_confirmed=printed_confirmed,
            page_count=pin["page_count"],
            reason=reason,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        return {"id": str(row.pk), "number": row.number, "state": "PROPOSED"}


@mutation_service
def act(
    *, case_id, subject_id, provider, citation_id, action, confirmed, synthetic_fixtures_only=False
):
    _enabled()
    if confirmed is not True or action not in {"CONFIRM", "WITHDRAW"}:
        raise cases.CaseConflict("pdf_human_confirmation_required")
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        row = (
            PdfCitation.objects.filter(pk=cases._uuid(citation_id), case=case)
            .select_related("answer")
            .first()
        )
        if row is None:
            raise cases.CaseConflict("pdf_citation_unavailable")
        _latest(row)
        state = _state(row)
        if state == "WITHDRAWN" or action == "CONFIRM" and state != "PROPOSED":
            raise cases.CaseConflict("pdf_transition_invalid")
        if action == "CONFIRM":
            if row.answer_id != _draft(case).pk:
                raise cases.CaseConflict("pdf_answer_changed")
            _validate(row, case, actor, provider)
        _identity(case, actor, provider)
        PdfCitationAction.objects.create(
            citation=row,
            action=action,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        return {"id": str(row.pk), "state": _state(row)}


@mutation_service
def open_pdf(
    *,
    case_id,
    subject_id,
    provider,
    citation_id,
    review=False,
    page_only=False,
    synthetic_fixtures_only=False,
):
    _enabled()
    if type(review) is not bool or type(page_only) is not bool:
        raise cases.CaseConflict("pdf_review_invalid")
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        row = (
            PdfCitation.objects.filter(pk=cases._uuid(citation_id), case=case)
            .select_related("answer")
            .first()
        )
        if row is None:
            raise cases.CaseConflict("pdf_citation_unavailable")
        _latest(row)
        if not _current(case, row) or _state(row) not in (
            {"PROPOSED", "CONFIRMED"} if review else {"CONFIRMED"}
        ):
            raise cases.CaseConflict("pdf_current_confirmation_required")
        if review and _draft(case).pk != row.answer_id:
            raise cases.CaseConflict("pdf_answer_changed")
        raw = _validate(row, case, actor, provider)
        if page_only:
            # Convert inside the scoped case transaction. Late rights or identity
            # changes must be rechecked AFTER the isolated parser has finished.
            from .page_preview import PdfPageUnavailable, selected_page

            try:
                raw = selected_page(
                    raw, page_number=row.page_number, page_count=row.page_count
                )
            except PdfPageUnavailable as exc:
                raise cases.CaseConflict("pdf_selected_page_unavailable") from exc
        _rights(case, actor, provider, row.snapshot)
        _identity(case, actor, provider)
        return {
            "raw": raw,
            "media_type": row.snapshot["media_type"],
            "filename": (
                f"selected-page-{row.page_number}.pdf"
                if page_only
                else row.snapshot["filename"]
            ),
            "page_number": row.page_number,
            "printed_label": row.printed_label,
            "page_count": row.page_count,
            "page_only": page_only,
        }


@projection_expiry_guard()
def for_locked_answer(*, answer, actor, provider):
    """Integrator hook before canonical approval/use; no automatic relation cloning.

    Caller holds the authorized case lock. Missing/pending/withdrawn/superseded
    references cannot be used as current citations. This never grants approval.
    """
    _enabled()
    if not connection.in_atomic_block:
        raise cases.CaseConflict("pdf_case_lock_required")
    case = answer.case
    if answer.revision != case.answer_revision or answer.evidence_version != case.evidence_version:
        raise cases.CaseConflict("pdf_answer_changed")
    output = []
    for row in PdfCitation.objects.filter(answer=answer).select_related("answer"):
        if PdfCitation.objects.filter(series=row.series, number__gt=row.number).exists():
            continue
        if not _current(case, row) or _state(row) != "CONFIRMED":
            raise cases.CaseConflict("pdf_current_confirmation_required")
        _validate(row, case, actor, provider)
        output.append(
            {
                "id": str(row.pk),
                "source": row.snapshot,
                "page_number": row.page_number,
                "printed_label": row.printed_label,
                "number": row.number,
            }
        )
    # Final pass prevents a multi-row result outliving permissions checked earlier.
    for item in output:
        _rights(case, actor, provider, item["source"])
    _identity(case, actor, provider)
    return output


@mutation_service
def desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    with (
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        projection_expiry_guard(),
    ):
        sources = []
        owners = [
            ("ATTACHMENT", pk)
            for pk in CaseAttachment.objects.filter(case=case, kind="pdf").values_list(
                "pk", flat=True
            )
        ]
        owners += [
            ("ANSWER_MEDIA", pk)
            for pk in AnswerPart.objects.filter(
                manifest__answer__case=case,
                manifest__answer__revision=case.answer_revision,
                kind="FILE",
                media_type="application/pdf",
            ).values_list("pk", flat=True)
        ]
        for kind, identifier in owners[:64]:
            try:
                sources.append(_source(case, actor, provider, kind, identifier)[0])
            except cases.CaseConflict:
                continue
        history = []
        seen = set()
        for row in (
            PdfCitation.objects.filter(case=case)
            .select_related("answer")
            .order_by("series", "-number")
        ):
            latest = row.series not in seen
            seen.add(row.series)
            entry = {
                "id": str(row.pk),
                "number": row.number,
                "state": _state(row),
                "current": _current(case, row),
                "latest": latest,
                "source": None,
                "reason": "",
                "page_number": None,
                "printed_label": "",
            }
            try:
                _validate(row, case, actor, provider)
                entry.update(
                    source=row.snapshot,
                    page_number=row.page_number,
                    printed_label=row.printed_label,
                )
                # A correction reason may refer to the previous document.
                if row.previous_id:
                    _validate(row.previous, case, actor, provider)
                entry["reason"] = row.reason
            except cases.CaseConflict:
                pass
            history.append(entry)
        for pin in sources:
            _rights(case, actor, provider, pin)
        for entry in history:
            if entry["source"] is not None:
                _rights(case, actor, provider, entry["source"])
        _identity(case, actor, provider)
        return {
            "public_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "sources": sources,
            "history": history,
            "answer_revision": case.answer_revision,
            "can_propose": case.stage == "UNDER_REVIEW" and not case.approved_answer_id,
        }
