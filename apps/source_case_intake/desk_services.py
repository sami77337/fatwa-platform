"""Scoped projections for the source desk; no new roles or identity grants."""

from django.db.models import Q

from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import resolve_identity

from . import services as intake
from .adapters import IntakeError
from .models import AttachmentBinding, EvidenceBinding, ReviewTicket, SourceReceipt

PAGE_SIZE = 25
STATUS_LABELS = {
    "PENDING": "محفوظ بانتظار المعالجة",
    "NEEDS_REVIEW": "بحاجة إلى مراجعة بشرية",
    "CREATED": "أنشئت قضية مستقلة",
    "FOLLOWUP": "أُلحق تعقيب بالقضية",
}
REASONS = {
    "parent_unresolved": "الرسالة السابقة غير مرتبطة بقضية معروفة",
    "source_identity_or_thread_mismatch": "هوية السائل أو موضوع المحادثة مختلف",
    "case_capability_required": "يلزم رمز وصول حالي للقضية قبل الإلحاق",
    "unthreaded_message_requires_review": "رسالة لاحقة دون رابط رد صريح؛ يلزم اختيار بشري",
    "message_already_bound": "الرسالة مرتبطة سابقًا؛ لا يجوز تكرار وقائعها",
    "event_idempotency_conflict": "وصلت بايتات مختلفة بمعرّف الحدث نفسه؛ الأصل محفوظ",
    "source_edit_requires_review": "تعديل من المصدر؛ لا يستبدل السؤال الأصلي",
    "invalid_or_incomplete_source": "صيغة ناقصة أو غير مدعومة؛ الأصل الخام محفوظ",
    "unsupported_media_requires_review": "نوع وسائط أو مجموعة رسائل غير مدعومة",
}


def _actor(subject_id, provider, ack):
    intake._guard(ack)
    return resolve_identity(provider, subject_id)


def _summary(row):
    result = intake._result(row)
    result.pop("token")
    return {
        **result,
        **intake._origin(row),
        "status_label": STATUS_LABELS[result["status"]],
        "reason_label": REASONS.get(result["reason"], "تحتاج هذه الرسالة إلى تحقق إضافي"),
    }


def inbox(
    *, subject_id, provider, source="all", state="all", page=1, synthetic_fixtures_only=False
):
    """Only scoped bound cases; unbound receipts require explicit review scope."""
    actor = _actor(subject_id, provider, synthetic_fixtures_only)
    if (
        source not in {"all", "telegram", "youtube", "website"}
        or state not in {"all", "review", "pending", "bound"}
        or type(page) is not int
        or not 1 <= page <= 10000
    ):
        raise IntakeError("invalid_inbox_filter")
    scope = Q(evidencebinding__case__public_ref__in=actor.case_keys)
    can_review = intake.REVIEW_SCOPE in actor.case_keys
    if can_review:
        scope |= Q(evidencebinding__isnull=True)
    rows = SourceReceipt.objects.filter(scope)
    if source != "all":
        rows = rows.filter(source=source)
    if state == "review":
        rows = rows.filter(evidencebinding__isnull=True, reviewticket__isnull=False)
    elif state == "pending":
        rows = rows.filter(evidencebinding__isnull=True, reviewticket__isnull=True)
    elif state == "bound":
        rows = rows.filter(evidencebinding__isnull=False)
    offset = (page - 1) * PAGE_SIZE
    selected = list(rows.order_by("received_at", "id")[offset : offset + PAGE_SIZE + 1])
    # Re-authorize every row against current provider state, not just the listing snapshot.
    visible = [
        detail(
            receipt_id=row.pk,
            subject_id=subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
            candidates=False,
        )["receipt"]
        for row in selected[:PAGE_SIZE]
    ]
    return {
        "receipts": visible,
        "source_filter": source,
        "state_filter": state,
        "page": page,
        "previous_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if len(selected) > PAGE_SIZE else None,
        "can_review": can_review,
    }


def detail(*, receipt_id, subject_id, provider, synthetic_fixtures_only=False, candidates=True):
    _actor(subject_id, provider, synthetic_fixtures_only)
    with synthetic_queue_atomic():
        row = intake._receipt(receipt_id)
        intake._lock(row.source, row.account)
        binding = EvidenceBinding.objects.filter(receipt=row).select_related("case").first()
        if binding:
            # Reviewer queue scope never substitutes for the bound case's scope.
            with cases._staff_case(binding.case_id, subject_id, provider, True):
                return {
                    "receipt": _summary(row),
                    "can_resolve": False,
                    "candidates": [],
                    "declared_files": row.attachments,
                    "linked_files": list(
                        AttachmentBinding.objects.filter(receipt=row).values(
                            "source_file_id",
                            "attachment_id",
                            "attachment__filename",
                            "attachment__sha256",
                            "attachment__evidence__version",
                        )
                    ),
                    "review_note": binding.review_note,
                    "reviewer": binding.subject_id,
                }
        actor = intake._reviewer(provider, subject_id)
        ticket = ReviewTicket.objects.filter(receipt=row).first()
        can_resolve = bool(ticket and not row.problem and ticket.reason != "message_already_bound")
        targets = []
        if candidates and can_resolve:
            targets = list(
                Case.objects.filter(
                    public_ref__in=actor.case_keys,
                    evidencebinding__receipt__source=row.source,
                    evidencebinding__receipt__account=row.account,
                    evidencebinding__receipt__conversation=row.conversation,
                    evidencebinding__receipt__thread=row.thread,
                    evidencebinding__receipt__sender=row.sender,
                )
                .distinct()
                .order_by("created_at")
                .values("id", "public_ref", "revision", "evidence_version")[:64]
            )
        return {
            "receipt": _summary(row),
            "can_resolve": can_resolve,
            "candidates": targets,
            "declared_files": row.attachments,
            "review_note": "",
            "reviewer": "",
        }


def timeline(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    """Canonical evidence order, retaining origin and file associations without copying facts."""
    _actor(subject_id, provider, synthetic_fixtures_only)
    with synthetic_queue_atomic():
        with cases._staff_case(case_id, subject_id, provider, True) as (case, _):
            origins = {
                b.evidence_id: b.receipt
                for b in EvidenceBinding.objects.filter(case=case).select_related("receipt")
            }
            metadata = {a["id"]: a for a in attachments._list(case)["attachments"]}
            files = {a.evidence_id: a for a in CaseAttachment.objects.filter(case=case)}
            source_files = {
                b.attachment_id: b
                for b in AttachmentBinding.objects.filter(attachment__case=case).select_related(
                    "receipt"
                )
            }
            items = []
            for evidence in case.evidence.order_by("version"):
                row = origins.get(evidence.pk)
                item = {
                    "version": evidence.version,
                    "text": evidence.text,
                    "created_at": evidence.created_at,
                    "origin": _summary(row) if row else None,
                }
                file = files.get(evidence.pk)
                if file:
                    item["file"] = metadata[str(file.pk)]
                    source_file = source_files.get(file.pk)
                    if source_file:
                        item["origin"] = _summary(source_file.receipt)
                        item["source_file_id"] = source_file.source_file_id
                items.append(item)
            return {
                "public_ref": case.public_ref,
                "case_id": str(case.pk),
                "revision": case.revision,
                "evidence_version": case.evidence_version,
                "timeline": items,
            }


def resume(*, receipt_id, subject_id, provider, synthetic_fixtures_only=False):
    """Resume the existing deterministic pipeline after a failed apply, never override review."""
    _actor(subject_id, provider, synthetic_fixtures_only)
    before = intake._reviewer(provider, subject_id)
    with synthetic_queue_atomic():
        row = intake._receipt(receipt_id)
        intake._lock(row.source, row.account)
        if (
            EvidenceBinding.objects.filter(receipt=row).exists()
            or ReviewTicket.objects.filter(receipt=row).exists()
        ):
            raise IntakeError("pending_receipt_required")
        result = intake.process(receipt_id=row.pk, synthetic_fixtures_only=True)
        after = intake._reviewer(provider, subject_id)
        if before.auth_epoch != after.auth_epoch:
            raise IntakeError("review_identity_changed")
        result.pop("token")
        return result
