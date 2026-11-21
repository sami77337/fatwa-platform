"""Offline intake services over V8 case/evidence/capability authority.

Capture commits before processing. A failed projection-to-case transaction leaves
the exact receipt pending and retryable. No source credentials or tokens persist.
"""

from dataclasses import asdict
from hashlib import sha256

from django.conf import settings
from django.db import connection, transaction

from apps.case_attachments import services as attachments
from apps.case_attachments.storage_bindings import binding_locks, raw_for_owner
from apps.casework import services as cases
from apps.casework.models import CaseEvidence
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity
from apps.platform_recovery.integration import mutation_service
from apps.private_media.storage import configured_storage

from .adapters import IntakeError, SourceContext, digest, project
from .models import (
    AttachmentBinding,
    EvidenceBinding,
    ReviewTicket,
    SourceReceipt,
    SourceReviewNote,
)

REVIEW_SCOPE = "source-intake-review"


def _guard(ack):
    if getattr(settings, "FATWA_SOURCE_CASE_INTAKE_ENABLED", False) is not True:
        raise IntakeError("source_intake_disabled")
    cases._guard(ack)


def _lock(source, account):
    # Serialize a source/account's receipt and parent-message correlations. All
    # service paths acquire this lock before a case lock, including human review.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,909))",
            [digest(source, account)],
        )


def _message_key(source, account, conversation, message_id):
    return digest(source, account, conversation, message_id)


@mutation_service
def capture(*, raw: bytes, context: SourceContext, synthetic_fixtures_only=False) -> SourceReceipt:
    """Persist immutable raw bytes, including invalid input and changed retries."""
    if connection.in_atomic_block:
        raise IntakeError("capture_requires_independent_commit")
    _guard(synthetic_fixtures_only)
    p = project(raw, context)
    values = asdict(p)
    values.update(
        source=context.source,
        account=context.account,
        event_key=digest(context.source, context.account, p.event_id),
        message_key=_message_key(context.source, context.account, p.conversation, p.message_id),
        requester_key="source:" + digest(context.source, context.account, p.sender),
        raw=raw,
        sha256=sha256(raw).hexdigest(),
    )
    with transaction.atomic():
        _lock(context.source, context.account)
        existing = SourceReceipt.objects.filter(
            event_key=values["event_key"], sha256=values["sha256"]
        ).first()
        if existing:
            if existing.conversation != p.conversation or existing.thread != p.thread:
                raise IntakeError("source_context_changed")
            return existing
        if SourceReceipt.objects.filter(event_key=values["event_key"]).exists():
            values["problem"] = "event_idempotency_conflict"
        return SourceReceipt.objects.create(**values)


def _receipt(receipt_id):
    row = SourceReceipt.objects.filter(pk=cases._uuid(receipt_id)).first()
    if row is None:
        raise IntakeError("receipt_unavailable")
    if sha256(bytes(row.raw)).hexdigest() != row.sha256:
        raise IntakeError("receipt_integrity_failed")
    return row


def _result(row, *, token=None):
    bound = EvidenceBinding.objects.filter(receipt=row).select_related("case", "evidence").first()
    review = ReviewTicket.objects.filter(receipt=row).first()
    return {
        "receipt_id": str(row.pk),
        "sha256": row.sha256,
        "status": bound.action if bound else ("NEEDS_REVIEW" if review else "PENDING"),
        "reason": review.reason if review else row.problem,
        "case_id": str(bound.case_id) if bound else None,
        "public_ref": bound.case.public_ref if bound else None,
        "evidence_version": bound.evidence.version if bound else None,
        "token": token,  # Only the initial case creation returns this one-time capability.
    }


def _review(row, reason):
    ReviewTicket.objects.get_or_create(receipt=row, defaults={"reason": reason})
    return _result(row)


def _bind(row, case_id, version, action, audit=None):
    EvidenceBinding.objects.create(
        receipt=row,
        message_key=row.message_key,
        case_id=case_id,
        evidence=CaseEvidence.objects.get(case_id=case_id, version=version),
        action=action,
        **(audit or {}),
    )


def _new_case(row, audit=None):
    result = cases.intake_case(
        original_question=row.original_text,
        source_event_id="source:" + str(row.pk),
        requester_id=row.requester_key,
        idempotency_key="source:" + row.message_key,
        synthetic_fixtures_only=True,
    )
    _bind(row, result["case_id"], 1, "CREATED", audit)
    return _result(row, token=result["token"])


def _same_origin(row, parent):
    return (row.source, row.account, row.conversation, row.thread, row.sender) == (
        parent.source,
        parent.account,
        parent.conversation,
        parent.thread,
        parent.sender,
    )


def _followup(row, case_id, token, audit=None):
    # Reuse the existing capability validation, revocation, case lock and approval
    # invalidation. Never mint a new capability merely because a source ID matches.
    with cases._token_case(token, True) as case:
        if case.pk != case_id or case.requester_id != row.requester_key:
            raise IntakeError("source_case_identity_mismatch")
        result = cases.add_followup(
            token=token,
            text=row.original_text,
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        _bind(row, case.pk, result["evidence_version"], "FOLLOWUP", audit)
    return _result(row)


@mutation_service
def process(*, receipt_id, token=None, synthetic_fixtures_only=False):
    """Apply once, or preserve a review ticket; safe to retry after process failure."""
    _guard(synthetic_fixtures_only)
    with synthetic_queue_atomic():
        row = _receipt(receipt_id)
        _lock(row.source, row.account)
        if EvidenceBinding.objects.filter(receipt=row).exists():
            return _result(row)
        if ReviewTicket.objects.filter(receipt=row).exists():
            return _result(row)
        if row.problem:
            return _review(row, row.problem)
        if EvidenceBinding.objects.filter(message_key=row.message_key).exists():
            return _review(row, "message_already_bound")
        if not row.parent_id:
            if EvidenceBinding.objects.filter(
                receipt__source=row.source,
                receipt__account=row.account,
                receipt__conversation=row.conversation,
                receipt__thread=row.thread,
                receipt__sender=row.sender,
            ).exists():
                return _review(row, "unthreaded_message_requires_review")
            return _new_case(row)
        parent = (
            EvidenceBinding.objects.select_related("receipt")
            .filter(
                message_key=_message_key(row.source, row.account, row.conversation, row.parent_id)
            )
            .first()
        )
        if parent is None:
            return _review(row, "parent_unresolved")
        if not _same_origin(row, parent.receipt):
            return _review(row, "source_identity_or_thread_mismatch")
        if token is None:
            return _review(row, "case_capability_required")
        return _followup(row, parent.case_id, token)


@mutation_service
def ingest(*, raw, context, token=None, synthetic_fixtures_only=False):
    """Trusted offline entry point. No webhook signature verification is implied."""
    if connection.in_atomic_block:
        raise IntakeError("capture_requires_independent_commit")
    row = capture(raw=raw, context=context, synthetic_fixtures_only=synthetic_fixtures_only)
    return process(receipt_id=row.pk, token=token, synthetic_fixtures_only=synthetic_fixtures_only)


def _reviewer(provider, subject_id):
    try:
        return resolve_identity(provider, subject_id, case_key=REVIEW_SCOPE)
    except IdentityUnavailable as exc:
        raise IntakeError("source_review_access_denied") from exc


@mutation_service
def review_queue(*, subject_id, provider, synthetic_fixtures_only=False):
    _guard(synthetic_fixtures_only)
    _reviewer(provider, subject_id)
    rows = SourceReceipt.objects.filter(
        reviewticket__isnull=False, evidencebinding__isnull=True
    ).order_by("received_at", "id")[:100]
    return [{**_result(row), **_origin(row)} for row in rows]


@mutation_service
def resolve_review(
    *,
    receipt_id,
    action,
    note,
    subject_id,
    provider,
    case_id=None,
    token=None,
    expected_revision=None,
    expected_evidence_version=None,
    expected_notes_version=None,
    synthetic_fixtures_only=False,
):
    """A scoped human may resolve correlation only, never a source edit/conflict.

    NEW_CASE explicitly separates an unresolved reply. FOLLOWUP additionally
    requires an existing same-origin binding, case scope and current capability.
    """
    _guard(synthetic_fixtures_only)
    cases._text(note)
    if action not in ("NEW_CASE", "FOLLOWUP"):
        raise IntakeError("invalid_review_action")
    before = _reviewer(provider, subject_id)
    with synthetic_queue_atomic():
        row = _receipt(receipt_id)
        _lock(row.source, row.account)
        identity = _reviewer(provider, subject_id)
        if before.auth_epoch != identity.auth_epoch:
            raise IntakeError("review_identity_changed")
        if EvidenceBinding.objects.filter(receipt=row).exists():
            raise IntakeError("receipt_already_resolved")
        ticket = ReviewTicket.objects.filter(receipt=row).first()
        if ticket is None or row.problem or ticket.reason == "message_already_bound":
            raise IntakeError("correlation_review_required")
        if (
            expected_notes_version is not None
            and row.review_notes.count() != expected_notes_version
        ):
            raise IntakeError("source_notes_changed")
        disposition = (
            SourceReviewNote.objects.filter(receipt=row, kind__in=["HOLD", "REOPEN"])
            .order_by("-sequence")
            .first()
        )
        if disposition and disposition.kind == "HOLD":
            raise IntakeError("source_review_on_hold")
        audit = dict(
            subject_id=identity.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=identity.auth_epoch,
            review_note=note,
        )
        if action == "NEW_CASE":
            result = _new_case(row, audit)
        else:
            with cases._staff_case(case_id, subject_id, provider, True) as (case, case_identity):
                if expected_revision is not None or expected_evidence_version is not None:
                    cases._mutation_versions(expected_revision, expected_evidence_version)
                    cases._versions(case, expected_revision, expected_evidence_version)
                origins = EvidenceBinding.objects.filter(case=case).select_related("receipt")
                if not any(_same_origin(row, bound.receipt) for bound in origins):
                    raise IntakeError("source_case_identity_mismatch")
                result = _followup(row, case.pk, token, audit)
                current = cases._identity(provider, subject_id, case)
                if current.auth_epoch != case_identity.auth_epoch:
                    raise IntakeError("review_identity_changed")
        after = _reviewer(provider, subject_id)
        if after.auth_epoch != identity.auth_epoch or provider.provider_id != audit["provider_id"]:
            raise IntakeError("review_identity_changed")
        return result


@mutation_service
def attach_fixture(
    *,
    receipt_id,
    source_file_id,
    token,
    raw,
    filename,
    media_type,
    expected_revision=None,
    expected_evidence_version=None,
    staff_subject_id=None,
    staff_provider=None,
    synthetic_fixtures_only=False,
):
    """Bind explicitly supplied synthetic bytes through the existing V8 upload API.

    A source file ID is metadata, not a download URL or proof of retrieval. This
    method performs no network access and never bypasses V8 validation or limits.
    """
    _guard(synthetic_fixtures_only)
    checked = attachments._validate(raw, filename, media_type)
    storage = configured_storage()
    with binding_locks(storage, [checked.sha256]), synthetic_queue_atomic():
        row = _receipt(receipt_id)
        _lock(row.source, row.account)
        bound = EvidenceBinding.objects.filter(receipt=row).first()
        if bound is None or source_file_id not in [a["source_file_id"] for a in row.attachments]:
            raise IntakeError("declared_bound_attachment_required")
        with cases._token_case(token, True) as case:
            if case.pk != bound.case_id:
                raise IntakeError("source_case_identity_mismatch")
            identity = None
            if staff_subject_id is not None or staff_provider is not None:
                identity = cases._identity(staff_provider, staff_subject_id, case)
            if expected_revision is not None or expected_evidence_version is not None:
                cases._mutation_versions(expected_revision, expected_evidence_version)
                cases._versions(case, expected_revision, expected_evidence_version)
            existing = (
                AttachmentBinding.objects.filter(receipt=row, source_file_id=source_file_id)
                .select_related("attachment")
                .first()
            )
            if existing:
                stored = existing.attachment
                if (raw_for_owner(stored), stored.filename, stored.media_type) != (
                    raw,
                    filename,
                    checked.media_type,
                ):
                    raise IntakeError("attachment_idempotency_conflict")
                return {"id": str(stored.pk), "sha256": stored.sha256, "created": False}
            result = attachments.upload(
                token=token,
                raw=raw,
                filename=filename,
                media_type=media_type,
                expected_revision=case.revision,
                synthetic_fixtures_only=True,
            )
            AttachmentBinding.objects.create(
                receipt=row, source_file_id=source_file_id, attachment_id=result["id"]
            )
            if identity is not None:
                current = cases._identity(staff_provider, staff_subject_id, case)
                if current.auth_epoch != identity.auth_epoch:
                    raise IntakeError("review_identity_changed")
            return {**result, "created": True}


def _origin(row):
    return {
        "receipt_id": str(row.pk),
        "source": row.source,
        "account": row.account,
        "event_id": row.event_id,
        "message_id": row.message_id,
        "conversation": row.conversation,
        "thread": row.thread,
        "sender": row.sender,
        "display_name": row.display_name,
        "parent_id": row.parent_id,
        "original_text": row.original_text,
        "sha256": row.sha256,
        "received_at": row.received_at,
    }


@mutation_service
def staff_origins(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    """Authorized desk projection; source IDs are text, never trusted HTML/URLs."""
    _guard(synthetic_fixtures_only)
    with cases._staff_case(case_id, subject_id, provider, True) as (case, _):
        from apps.data_privacy.integration import allowed as privacy_allowed

        bindings = EvidenceBinding.objects.filter(case=case).select_related("receipt", "evidence")
        return [
            {
                **_origin(b.receipt),
                "evidence_version": b.evidence.version,
                "attachments": list(
                    item for item in AttachmentBinding.objects.filter(receipt=b.receipt).values(
                        "source_file_id", "attachment_id"
                    ) if privacy_allowed("ATTACHMENT", item["attachment_id"])
                ),
            }
            for b in bindings.order_by("evidence__version")
            if privacy_allowed("SOURCE_RECEIPT", b.receipt_id)
        ]


@mutation_service
def staff_raw(*, receipt_id, subject_id, provider, synthetic_fixtures_only=False, usage="EXPORT"):
    from apps.data_privacy.integration import projection
    from apps.data_privacy.integration import staff as privacy

    _guard(synthetic_fixtures_only)
    if usage not in {"READ", "EXPORT"}:
        raise IntakeError("source_raw_usage_invalid")
    row = _receipt(receipt_id)
    bound = EvidenceBinding.objects.filter(receipt=row).first()
    if bound:
        with cases._staff_case(bound.case_id, subject_id, provider, True) as (_, actor):
            privacy("SOURCE_RECEIPT", row.pk, actor=actor, provider=provider, action=usage)
            return bytes(row.raw)
    with projection():
        actor = _reviewer(provider, subject_id)
        privacy("SOURCE_RECEIPT", row.pk, actor=actor, provider=provider, action=usage)
        return bytes(row.raw)
