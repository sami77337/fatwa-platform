"""Synthetic intake: pure validation, exact source provenance, one guarded write unit.

Original bytes/slices are authoritative. D1 sees only a field-type validation
projection: non-string numbers cannot become IDs or source evidence. No catalog
seed, numeric arithmetic, reference verification, media/network or review action.
"""
from collections import Counter
from dataclasses import dataclass
import json
import re
from uuid import UUID

from apps.prepared_pipeline import prepare_batch
from apps.fatwa_drafts.intake import ValidationError
from . import contracts as c, fixtures
from .contracts import ParsedPayload, SourceSlice


@dataclass(frozen=True, slots=True)
class CheckedItem:
    row_ordinal: int
    external_id: str | None
    question_original: str | None
    source: SourceSlice
    intake_status: str
    validation_results: dict
    references: tuple[SourceSlice, ...]


@dataclass(frozen=True, slots=True)
class CheckedIntake:
    parsed: ParsedPayload
    items: tuple[CheckedItem, ...]

    def report(self) -> dict:
        return dict(status='CHECKED', payload_sha256=self.parsed.payload_sha256,
            scope=c.SYNTHETIC_SCOPE, source_config_id=c.SOURCE_CONFIG_ID,
            item_count=len(self.items), reference_count=sum(len(i.references) for i in self.items),
            summary=dict(Counter(i.intake_status for i in self.items)),
            items=[dict(row_ordinal=i.row_ordinal, intake_status=i.intake_status,
                        reference_count=len(i.references), validation_results=i.validation_results)
                   for i in self.items])


@dataclass(frozen=True, slots=True)
class IntakeResult:
    batch_id: UUID
    decision: c.IdempotencyDecision
    payload_sha256: str
    item_count: int
    reference_count: int
    summary: dict[str, int]

    def report(self) -> dict:
        return dict(status='IMPORTED', batch_id=str(self.batch_id), decision=self.decision.value,
                    payload_sha256=self.payload_sha256, scope=c.SYNTHETIC_SCOPE,
                    source_config_id=c.SOURCE_CONFIG_ID, item_count=self.item_count,
                    reference_count=self.reference_count, summary=self.summary)


def _validation_row(row):
    """Bounded D1 type projection, never the storage/source representation.

    Every accepted D1 field is text or a list of text-valued pointer dicts.
    Invalid scalar/numeric values become invalid nulls in this disposable view;
    a Decimal/huge int is never converted to float, string, a numeric ID or zero.
    Unknown/nested values remain invalid fields without recursive serialization.
    """
    if not isinstance(row, dict):
        return None
    projected = {}
    for key, value in row.items():
        if key == 'reference_links' and isinstance(value, list):
            projected[key] = [
                {k: v if isinstance(v, str) else None for k, v in pointer.items()}
                if isinstance(pointer, dict) else None for pointer in value]
        else:
            projected[key] = value if isinstance(value, str) else None
    return projected


def check_intake(raw: bytes, *, synthetic_fixtures_only: bool = False) -> CheckedIntake:
    """Pure check: all rows retained, exact slices, no database/files/network.

    Malformed envelopes raise ContractError. Per-row failures become BLOCKED_INVALID.
    Readiness is D1 classification, independent of reference/source verification.
    """
    parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=synthetic_fixtures_only)
    ids = Counter(row['external_id'] for row in parsed.items if isinstance(row, dict)
                  and isinstance(row.get('external_id'), str))
    reference_map = fixtures.trusted_reference_map()
    items = []
    for ordinal, row in enumerate(parsed.items, 1):
        validation_raw = json.dumps(dict(schema=c.PREPARED_SCHEMA, items=[_validation_row(row)]),
                                    ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        try:
            prepared = prepare_batch(validation_raw, synthetic_fixtures_only=True,
                                     reference_map=reference_map, catalog=None).report['items'][0]
            findings = list(prepared['findings'])
            statuses = list(prepared['statuses'])
        except ValidationError:
            # Only an individually invalid/oversized validation projection can
            # reach this path; accepted original source still remains untouched.
            findings = [dict(field='', code='D1_validation_rejected', severity='error')]
            statuses = ['blocked-invalid', 'references-unverified']
        external_id = c.valid_external_id(row.get('external_id')) if isinstance(row, dict) else None
        if external_id is None:
            findings.append(dict(field='external_id', code='invalid_external_id', severity='error'))
        elif ids[external_id] > 1:
            findings.append(dict(field='external_id', code='duplicate_id', severity='error'))
        status = (c.IntakeStatus.BLOCKED_INVALID if any(f['severity']=='error' for f in findings)
                  else c.IntakeStatus.NEEDS_REVIEW if 'needs-editor-review' in statuses
                  else c.IntakeStatus.READY_FOR_EDITOR)
        question = row.get('question') if isinstance(row, dict) else None
        items.append(CheckedItem(ordinal, external_id, question if isinstance(question,str) else None,
            parsed.item_sources[ordinal-1], status.value,
            dict(findings=findings, prepared_statuses=statuses,
                 reference_verification='UNVERIFIED', human_editing_performed=False),
            parsed.reference_sources[ordinal-1]))
    return CheckedIntake(parsed, tuple(items))


def _existing_batch(idempotency_key, using):
    from .models import IntakeBatch
    return IntakeBatch.objects.using(using).filter(scope=c.SYNTHETIC_SCOPE,
                                                  idempotency_key=idempotency_key).first()


def _result(batch, decision, using):
    from django.db.models import Count
    from .models import IntakeReference
    summary = {r['intake_status']:r['count'] for r in batch.items.using(using)
               .values('intake_status').annotate(count=Count('id'))}
    return IntakeResult(batch.pk, decision, batch.payload_sha256, sum(summary.values()),
        IntakeReference.objects.using(using).filter(intake_item__batch_id=batch.pk).count(), summary)


def import_intake(raw: bytes, *, idempotency_key: str, synthetic_fixtures_only: bool = False,
                  using: str = 'default') -> IntakeResult:
    """All-or-nothing persistence; guard precedes the one outer transaction.

    Same fixed-scope key/hash replays existing persisted metadata. A changed hash
    raises existing IdempotencyConflict (409) without mutation. A concurrent unique
    insert is recovered only after rollback of its inner savepoint; other DB errors
    propagate and roll back the full write unit. No caller scope/map/config accepted.
    """
    checked = check_intake(raw, synthetic_fixtures_only=synthetic_fixtures_only)
    if not isinstance(idempotency_key,str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',idempotency_key) is None:
        raise c.ContractError('idempotency: bounded_ascii_key_required')
    from django.db import IntegrityError, transaction
    from . import guards

    with guards.synthetic_atomic(synthetic_fixtures_only=synthetic_fixtures_only, using=using):
        # Default/public settings fail in the shared guard before importing the
        # deliberately unregistered workflow models, never via a model crash.
        from .models import IntakeBatch, IntakeItem, IntakeReference
        existing = _existing_batch(idempotency_key, using)
        if existing is not None:
            decision = c.idempotency_decision(existing.payload_sha256, checked.parsed.payload_sha256)
            return _result(existing, decision, using)
        try:
            # The sole additional atomic block is a uniqueness-race savepoint.
            with transaction.atomic(using=using):
                batch = IntakeBatch.objects.using(using).create(idempotency_key=idempotency_key,
                    payload_sha256=checked.parsed.payload_sha256, original_payload=checked.parsed.raw)
        except IntegrityError as exc:
            if getattr(getattr(exc.__cause__,'diag',None),'constraint_name',None) != 'w7_batch_scope_key_unique':
                raise
            existing = _existing_batch(idempotency_key, using)
            if existing is None:
                raise
            decision = c.idempotency_decision(existing.payload_sha256, checked.parsed.payload_sha256)
            return _result(existing, decision, using)
        stored = [IntakeItem(batch=batch, row_ordinal=i.row_ordinal, external_id=i.external_id,
            question_original=i.question_original, original_row=i.source.text,
            source_byte_start=i.source.start, source_byte_end=i.source.end,
            intake_status=i.intake_status, review_status=c.ReviewStatus.UNREVIEWED.value,
            validation_results=i.validation_results) for i in checked.items]
        IntakeItem.objects.using(using).bulk_create(stored, batch_size=100)
        for item, source in zip(stored, checked.items, strict=True):
            if source.references:
                IntakeReference.objects.using(using).bulk_create([
                    IntakeReference(intake_item=item, reference_ordinal=ordinal, original_pointer=pointer.text,
                        source_byte_start=pointer.start, source_byte_end=pointer.end,
                        reference_status=c.ReferenceStatus.UNVERIFIED.value,
                        verification_results={'reasons':['not_verified_during_intake']},
                        verified_identity={}, citation_text='')
                    for ordinal, pointer in enumerate(source.references,1)], batch_size=100)
        return _result(batch, c.IdempotencyDecision.CREATE, using)
