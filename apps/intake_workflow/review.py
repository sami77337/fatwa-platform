"""Synthetic persisted review only: one guarded write unit, no HTTP mutations.

Reads use exact source slices and separate intake/reference/review states. No
external ID is a selection key, and no answer/approval/publishing action exists.
"""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db.models import Q

from . import contracts as c, guards


class ReviewConflict(c.ContractError):
    code = 'REVIEW_CONFLICT'
    status_code = 409


class ReviewNotFound(c.ContractError):
    code = 'REVIEW_NOT_FOUND'
    status_code = 404


def _uuid(value):
    if type(value) is UUID:
        return value
    if isinstance(value, str) and len(value) == 36:
        try:
            result = UUID(value)
            if str(result) == value:
                return result
        except ValueError:
            pass
    raise c.ContractError('review: canonical_uuid_required')


def _reason(value):
    if not isinstance(value, str) or not 1 <= len(value) <= c.MAX_REASON_CHARS or not value.strip() or '\x00' in value:
        raise c.ContractError('review: invalid_reason')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise c.ContractError('review: invalid_reason') from exc
    return value


@dataclass(frozen=True, slots=True)
class ReviewTransitionResult:
    item_id: UUID
    event_id: UUID
    operation_id: UUID
    from_status: str
    to_status: str
    replayed: bool


def transition_review(item_id, *, operation_id, action: str, expected_status: str,
                      reason: str, synthetic_fixtures_only: bool = False,
                      using: str = 'default') -> ReviewTransitionResult:
    item_id, operation_id = _uuid(item_id), _uuid(operation_id)
    reason = _reason(reason)
    try:
        action, expected_status = c.ReviewAction(action).value, c.ReviewStatus(expected_status).value
    except (ValueError, TypeError) as exc:
        raise c.ContractError('review: invalid_action_or_status') from exc
    # The sole guard runs before transaction.atomic(); commands must not wrap it.
    with guards.synthetic_atomic(synthetic_fixtures_only=synthetic_fixtures_only, using=using):
        from .models import IntakeItem, ReviewEvent
        try:
            item = IntakeItem.objects.using(using).select_for_update(of=('self',)).get(
                id=item_id, batch__scope=c.SYNTHETIC_SCOPE, batch__source_config_id=c.SOURCE_CONFIG_ID)
        except IntakeItem.DoesNotExist as exc:
            raise ReviewNotFound('review: item_not_found') from exc
        event = ReviewEvent.objects.using(using).filter(intake_item=item, operation_id=operation_id).first()
        if event is not None:
            if (event.action, event.from_status, event.reason) != (action, expected_status, reason):
                raise ReviewConflict('review: operation_conflict')
            replayed = True
        else:
            if item.review_status != expected_status:
                raise ReviewConflict('review: stale_status')
            target = c.next_review_status(item.review_status, action).value
            item.review_status = target
            item.save(using=using, update_fields=['review_status'])
            event = ReviewEvent.objects.using(using).create(intake_item=item, operation_id=operation_id,
                action=action, from_status=expected_status, to_status=target, reason=reason)
            replayed = False
        return ReviewTransitionResult(item.id, event.id, event.operation_id,
                                      event.from_status, event.to_status, replayed)


@dataclass(frozen=True, slots=True)
class ReviewBatchOption:
    id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredReference:
    id: UUID
    original_pointer: str
    source_byte_start: int
    source_byte_end: int
    reference_status: str
    citation_text: str


@dataclass(frozen=True, slots=True)
class StoredReviewEvent:
    id: UUID
    operation_id: UUID
    action: str
    from_status: str
    to_status: str
    reason: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredReviewRow:
    id: UUID
    batch_id: UUID
    row_ordinal: int
    external_id: str | None
    question: str | None
    original_row: str
    source_byte_start: int
    source_byte_end: int
    intake_status: str
    review_status: str
    prepared_clip_url: str | None
    references: tuple[StoredReference, ...]
    events: tuple[StoredReviewEvent, ...] = ()
    events_truncated: bool = False


@dataclass(frozen=True, slots=True)
class ReviewWorklist:
    batches: tuple[ReviewBatchOption, ...]
    batch_id: UUID | None
    rows: tuple[StoredReviewRow, ...]
    row: StoredReviewRow | None
    total_count: int
    matched_count: int
    page: int
    page_count: int
    page_size: int
    q: str
    intake_status: str
    review_status: str


def _read_parameters(batch_id, row_id, q, intake_status, review_status, page, page_size):
    batch_id = _uuid(batch_id) if batch_id is not None else None
    row_id = _uuid(row_id) if row_id is not None else None
    if (row_id is not None and batch_id is None or not isinstance(q, str) or len(q) > 80
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in q)
            or intake_status not in ('', *c.IntakeStatus) or review_status not in ('', *c.ReviewStatus)
            or type(page) is not int or not 1 <= page <= 10000
            or type(page_size) is not int or not 1 <= page_size <= 50):
        raise c.ContractError('review: invalid_query')
    try:
        q.encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise c.ContractError('review: invalid_query') from exc
    return batch_id, row_id


def load_review_worklist(*, batch_id=None, row_id=None, q: str = '', intake_status: str = '',
                         review_status: str = '', page: int = 1, page_size: int = 20,
                         synthetic_fixtures_only: bool = False, using: str = 'default') -> ReviewWorklist:
    batch_id, row_id = _read_parameters(batch_id, row_id, q, intake_status, review_status, page, page_size)
    # No write tag/transaction is opened for reads. Ownership/flags precede ORM.
    guards.require_owned_database(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    from .models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent
    batches = IntakeBatch.objects.using(using).filter(scope=c.SYNTHETIC_SCOPE, source_config_id=c.SOURCE_CONFIG_ID)
    options = list(batches.only('id', 'created_at').order_by('-created_at', 'id')[:100])
    if batch_id is None:
        batch_id = options[0].id if options else None
    if batch_id is None:
        if page != 1:
            raise ReviewNotFound('review: page_not_found')
        return ReviewWorklist((), None, (), None, 0, 0, page, 1, page_size, q, intake_status, review_status)
    try:
        batch = batches.get(id=batch_id)
    except IntakeBatch.DoesNotExist as exc:
        raise ReviewNotFound('review: batch_not_found') from exc
    if batch.id not in {option.id for option in options}:
        options.append(batch)
    parsed = c.parse_synthetic_payload(bytes(batch.original_payload), synthetic_fixtures_only=True)
    if parsed.payload_sha256 != batch.payload_sha256:
        raise c.ContractError('review: source_integrity_mismatch')
    items = IntakeItem.objects.using(using).filter(batch_id=batch_id).order_by('row_ordinal')
    total_count = items.count()
    filtered = items
    if intake_status:
        filtered = filtered.filter(intake_status=intake_status)
    if review_status:
        filtered = filtered.filter(review_status=review_status)
    if q.strip():
        filtered = filtered.filter(Q(question_original__icontains=q.strip()) | Q(external_id__icontains=q.strip()))
    matched_count = filtered.count()
    page_count = max(1, (matched_count + page_size - 1) // page_size)
    if page > page_count:
        raise ReviewNotFound('review: page_not_found')
    selected = list(filtered[(page - 1)*page_size:page*page_size])
    detail = None
    if row_id is not None:
        try:
            detail = items.get(id=row_id)
        except IntakeItem.DoesNotExist as exc:
            raise ReviewNotFound('review: item_not_found') from exc
    chosen = {item.id: item for item in selected}
    if detail is not None:
        chosen[detail.id] = detail
    references = {}
    for reference in IntakeReference.objects.using(using).filter(intake_item_id__in=chosen).order_by('reference_ordinal'):
        references.setdefault(reference.intake_item_id, []).append(reference)
    events = list(ReviewEvent.objects.using(using).filter(intake_item_id=row_id).order_by('-created_at','-id')[:101]) if detail else []
    rendered = {}
    for item in chosen.values():
        if not 1 <= item.row_ordinal <= len(parsed.item_sources):
            raise c.ContractError('review: source_integrity_mismatch')
        source = parsed.item_sources[item.row_ordinal-1]
        if (item.original_row, item.source_byte_start, item.source_byte_end) != (source.text, source.start, source.end):
            raise c.ContractError('review: source_integrity_mismatch')
        source_refs = parsed.reference_sources[item.row_ordinal-1]
        refs = []
        for reference in references.get(item.id, []):
            if not 1 <= reference.reference_ordinal <= len(source_refs):
                raise c.ContractError('review: source_integrity_mismatch')
            pointer = source_refs[reference.reference_ordinal-1]
            if (reference.original_pointer, reference.source_byte_start, reference.source_byte_end) != (pointer.text, pointer.start, pointer.end):
                raise c.ContractError('review: source_integrity_mismatch')
            if reference.reference_status == 'VERIFIED':
                c.validate_verified_identity(reference.verified_identity)
            elif reference.citation_text or reference.verified_identity:
                raise c.ContractError('review: unverified_citation')
            refs.append(StoredReference(reference.id, pointer.text, pointer.start, pointer.end,
                                        reference.reference_status, reference.citation_text))
        original = parsed.items[item.row_ordinal-1]
        clip = original.get('prepared_clip_url') if isinstance(original, dict) else None
        history = tuple(StoredReviewEvent(e.id,e.operation_id,e.action,e.from_status,e.to_status,e.reason,e.created_at)
                        for e in events[:100]) if item.id == row_id else ()
        rendered[item.id] = StoredReviewRow(item.id,item.batch_id,item.row_ordinal,item.external_id,item.question_original,
            source.text,source.start,source.end,item.intake_status,item.review_status,
            clip if isinstance(clip,str) else None,tuple(refs),history,item.id == row_id and len(events)>100)
    return ReviewWorklist(tuple(ReviewBatchOption(b.id,b.created_at) for b in options),batch_id,
        tuple(rendered[item.id] for item in selected),rendered.get(row_id),total_count,matched_count,page,page_count,
        page_size,q,intake_status,review_status)
