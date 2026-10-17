"""Fixed synthetic reference verification; source text is never reconstructed.

The public write service owns one guarded unit, after E1 has committed intake.
Pure plans accept asserted catalog evidence; only the write service reads the
current owned database. Matching stored pins never attest archive inspection.
"""
from dataclasses import asdict, dataclass
from collections import Counter
from hashlib import sha256
from uuid import UUID

from . import contracts as c, fixtures
from .contracts import SourceSlice
from apps.reference_links.bridge import exact_text
from apps.reference_links.resolution import (
    CatalogReadError, Heading, KIND, Outcome, SnapshotCatalog, render_citation, resolve,
)


@dataclass(frozen=True, slots=True)
class ReferenceVerification:
    reference_ordinal: int
    source: SourceSlice
    status: c.ReferenceStatus
    reasons: tuple[str, ...]
    identity: tuple[tuple[str, object], ...] = ()
    evidence: Heading | None = None
    citation_text: str = ''

    def derived_values(self) -> dict:
        """Fresh JSON-safe derived fields only; decimals remain in source text."""
        provenance = asdict(self.evidence) if self.evidence else None
        if provenance is not None:
            provenance['path'] = list(self.evidence.path)
        return dict(reference_status=self.status.value,
            verification_results=dict(kind=KIND, reasons=list(self.reasons),
                source=asdict(self.source), source_sha256=sha256(self.source.text.encode()).hexdigest(),
                archive_inspected=False, provenance=provenance),
            verified_identity=dict(self.identity), citation_text=self.citation_text)


@dataclass(frozen=True, slots=True)
class ItemReferenceVerification:
    row_ordinal: int
    source: SourceSlice
    references: tuple[ReferenceVerification, ...]


@dataclass(frozen=True, slots=True)
class BatchReferenceVerification:
    batch_id: UUID
    payload_sha256: str
    items: tuple[ItemReferenceVerification, ...]


def _expected_heading(row: int) -> Heading:
    root = 'كِتَابٌ اصطناعي'
    title = {1: root, 2: 'بابٌ اصطناعي أول', 3: 'بابٌ اصطناعي ثان'}[row]
    return Heading(7001, row, 'مرجع اصطناعي لتجارب Wave7', title, 'الأول', 6 + row,
        (root,) if row == 1 else (root, title), c.SOURCE_IDENTITY['source_namespace'],
        '622', c.SOURCE_IDENTITY['source_input_sha256'], c.SOURCE_IDENTITY['edition_key'],
        c.SOURCE_IDENTITY['source_archive_sha256'])


def _configuration() -> dict[int, tuple[c.ReferenceStatus | None, str]]:
    """Require both fixed D1/D3 bindings; no caller/payload configuration path."""
    from apps.prepared_pipeline import C1Pointer
    config, reference_map = fixtures.trusted_bridge_config(), fixtures.trusted_reference_map()
    output = {}
    for identity in c.VERIFIED_IDENTITIES:
        row = identity['source_row_id']
        pointer = C1Pointer('W7-SOURCE', f'W7-HEADING-{row}')
        d1 = reference_map.get(pointer)
        d3 = next((h for h in config.headings if
                   (h.c1_source_id, h.c1_heading_id) == (pointer.source_id, pointer.heading_id)), None)
        if d1 is None or d3 is None:
            output[row] = c.ReferenceStatus.UNVERIFIED, 'trusted_configuration_missing'
        elif (asdict(config.edition.identity) != dict(c.SOURCE_IDENTITY)
              or config.edition.edition_id != identity['edition_id']
              or d3.c2_source_id != identity['source_id'] or d3.source_row_id != row
              or asdict(d1.c2) != {k: v for k, v in identity.items()
                                      if k not in ('edition_id', 'source_row_id')}
              or d1.edition_id != identity['edition_id'] or d1.source_row_id != row):
            output[row] = c.ReferenceStatus.MISMATCHED, 'trusted_configuration_conflict'
        else:
            output[row] = None, ''
    return output


def _pointer_row(pointer: object) -> tuple[int | None, c.ReferenceStatus, str]:
    if not isinstance(pointer, dict) or any(not isinstance(v, str) for v in pointer.values()):
        return None, c.ReferenceStatus.UNVERIFIED, 'invalid_pointer'
    try:
        for value in pointer.values():
            exact_text(value)
    except ValueError:
        return None, c.ReferenceStatus.UNVERIFIED, 'invalid_pointer'
    if set(pointer) == {'source_id', 'heading_id'}:
        for row in (1, 2, 3):
            if pointer == {'source_id': 'W7-SOURCE', 'heading_id': f'W7-HEADING-{row}'}:
                return row, c.ReferenceStatus.UNVERIFIED, ''
        return None, c.ReferenceStatus.UNVERIFIED, 'explicit_mapping_missing'
    if set(pointer) == {*c.SOURCE_IDENTITY, 'source_id'}:
        for identity in c.VERIFIED_IDENTITIES:
            expected = {k: v for k, v in identity.items() if k not in ('edition_id', 'source_row_id')}
            if pointer == expected:
                return identity['source_row_id'], c.ReferenceStatus.UNVERIFIED, ''
        return None, c.ReferenceStatus.MISMATCHED, 'source_identity_mismatch'
    return None, c.ReferenceStatus.UNVERIFIED, 'unsupported_pointer_shape'


def _plan(parsed: c.ParsedPayload, catalog_rows: tuple[Heading, ...], *,
          conflicting_source_rows: frozenset[int] = frozenset()) -> tuple[ItemReferenceVerification, ...]:
    if type(catalog_rows) is not tuple or any(type(row) is not Heading for row in catalog_rows):
        raise c.ContractError('reference: explicit_heading_snapshot_required')
    try:
        catalog = SnapshotCatalog(catalog_rows)
    except ValueError as error:
        raise c.ContractError('reference: invalid_heading_snapshot') from error
    config = _configuration()
    complete_configuration = all(status is None for status, _ in config.values())
    items = []
    for ordinal, (item, source, sources) in enumerate(zip(
            parsed.items, parsed.item_sources, parsed.reference_sources, strict=True), 1):
        links = item.get('reference_links', []) if isinstance(item, dict) else []
        if not isinstance(links, list):
            links = []
        # Only exact textual pointers are hashable association keys. Invalid
        # scalar/Decimal/huge-int values are never cast, compared or serialized.
        keys = [tuple(sorted(p.items())) if isinstance(p, dict)
                and all(isinstance(v, str) for v in p.values()) else None for p in links]
        counts = Counter(key for key in keys if key is not None)
        references = []
        for number, (pointer, pointer_source, key) in enumerate(zip(links, sources, keys, strict=True), 1):
            row, status, reason = _pointer_row(pointer)
            evidence, identity, citation = None, (), ''
            if key is not None and counts[key] > 1:
                row, status, reason = None, c.ReferenceStatus.UNVERIFIED, 'duplicate_pointer'
            if row is not None:
                config_status, config_reason = config[row]
                if row in conflicting_source_rows:
                    status, reason = c.ReferenceStatus.MISMATCHED, 'catalog_source_row_mismatch'
                elif config_status is not None:
                    status, reason = config_status, config_reason
                else:
                    resolution = resolve({'edition_id': 7001, 'source_row_id': row}, catalog)
                    if resolution.outcome != Outcome.VERIFIED:
                        reason = resolution.reasons[0]
                    else:
                        actual, expected = asdict(resolution.evidence), asdict(_expected_heading(row))
                        # Legacy Heading constructors omit just these optional
                        # fields. Complete explicit fixed bindings above remain
                        # mandatory; an explicit conflicting value never passes.
                        legacy = any(actual[field] is None for field in ('edition_key', 'source_archive_sha256'))
                        for field in ('edition_key', 'source_archive_sha256'):
                            if actual[field] is None:
                                actual[field] = expected[field]
                        if legacy and not complete_configuration:
                            status, reason = c.ReferenceStatus.UNVERIFIED, 'trusted_configuration_incomplete'
                        elif actual != expected:
                            status, reason = c.ReferenceStatus.MISMATCHED, 'catalog_metadata_mismatch'
                        else:
                            status, reason = c.ReferenceStatus.VERIFIED, ''
                            evidence = resolution.evidence
                            identity = tuple(c.validate_verified_identity(dict(c.VERIFIED_IDENTITIES[row - 1])).items())
                            citation = render_citation(resolution)
            references.append(ReferenceVerification(number, pointer_source, status,
                (reason,) if reason else (), identity, evidence, citation))
        items.append(ItemReferenceVerification(ordinal, source, tuple(references)))
    return tuple(items)


def plan_reference_verification(raw: bytes, *, synthetic_fixtures_only: bool = False,
                                catalog_rows: tuple[Heading, ...] = ()) -> tuple[ItemReferenceVerification, ...]:
    """Pure asserted-evidence plan; never opens a DB or rewrites numeric tokens."""
    parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=synthetic_fixtures_only)
    return _plan(parsed, catalog_rows)


def _check_source(instance, source: SourceSlice, field: str) -> None:
    if (getattr(instance, field) != source.text
            or instance.source_byte_start != source.start or instance.source_byte_end != source.end):
        raise c.ContractError('reference: persisted_source_mismatch')


def _catalog_projection_conflicts(rows) -> frozenset[int]:
    """Heading path titles alone cannot establish exact ancestor identities."""
    conflicts = set()
    for row, source_id, parent_row, parent_edition, parent_source_id, depth in rows:
        if type(row) is not int or row not in (1, 2, 3):
            raise c.ContractError('reference: unexpected_catalog_identity')
        expected = (c.VERIFIED_IDENTITIES[row - 1]['source_id'], None, None, None, 1) if row == 1 else (
            c.VERIFIED_IDENTITIES[row - 1]['source_id'], 1, 7001, 'wave7-title-1', 2)
        if (source_id, parent_row, parent_edition, parent_source_id, depth) != expected:
            conflicts.add(row)
    return frozenset(conflicts)


def verify_batch_references(batch_id: UUID, *, synthetic_fixtures_only: bool = False,
                            using: str = 'default') -> BatchReferenceVerification:
    """Update derived references in one owned unit, never inside E1's transaction.

    Intake/review statuses, events and all original text/offsets remain unchanged.
    Missing evidence is persisted UNVERIFIED; a database read failure aborts the
    whole unit without claiming success or keeping a partial set of new results.
    """
    if synthetic_fixtures_only is not True:
        raise c.ContractError('synthetic_acknowledgement_required')
    if type(batch_id) is not UUID:
        raise c.ContractError('reference: batch_uuid_required')
    from .guards import synthetic_atomic

    with synthetic_atomic(synthetic_fixtures_only=synthetic_fixtures_only, using=using):
        from .models import IntakeBatch, IntakeItem, IntakeReference
        from django.db import DatabaseError
        from apps.reference.models import ReferenceHeading
        from apps.reference_links.django_adapter import DjangoCatalog

        try:
            batch = IntakeBatch.objects.using(using).select_for_update().get(pk=batch_id)
        except IntakeBatch.DoesNotExist:
            raise c.ContractError('reference: batch_not_found') from None
        parsed = c.parse_synthetic_payload(bytes(batch.original_payload), synthetic_fixtures_only=True)
        if (batch.scope != c.SYNTHETIC_SCOPE or batch.source_config_id != c.SOURCE_CONFIG_ID
                or batch.contract_version != c.CONTRACT_VERSION
                or batch.payload_sha256 != parsed.payload_sha256
                or batch.payload_snapshot != parsed.raw.decode('utf-8')):
            raise c.ContractError('reference: persisted_batch_mismatch')
        items = list(IntakeItem.objects.using(using).select_for_update()
                     .filter(batch=batch).order_by('row_ordinal'))
        references = list(IntakeReference.objects.using(using).select_for_update()
            .filter(intake_item__batch=batch).order_by('intake_item__row_ordinal', 'reference_ordinal'))
        if [item.row_ordinal for item in items] != list(range(1, len(parsed.items) + 1)):
            raise c.ContractError('reference: persisted_item_alignment_mismatch')
        expected_references = []
        for item, source, sources in zip(items, parsed.item_sources, parsed.reference_sources, strict=True):
            _check_source(item, source, 'original_row')
            expected_references.extend((item.pk, number, source)
                                       for number, source in enumerate(sources, 1))
        if [(ref.intake_item_id, ref.reference_ordinal) for ref in references] != [
                (item, number) for item, number, _ in expected_references]:
            raise c.ContractError('reference: persisted_reference_alignment_mismatch')
        for reference, (_, _, source) in zip(references, expected_references, strict=True):
            _check_source(reference, source, 'original_pointer')
        required = set()
        for item in parsed.items:
            links = item.get('reference_links', []) if isinstance(item, dict) else []
            if isinstance(links, list):
                required.update(row for pointer in links if (row := _pointer_row(pointer)[0]) is not None)
        catalog_rows = []
        try:
            for row in sorted(required):
                catalog_rows.extend(DjangoCatalog().lookup(7001, row))
            # Heading's legacy result type does not carry opaque source_id.
            # Read it explicitly; never manufacture it from a numeric row ID.
            projection = tuple(ReferenceHeading.objects.using(using)
                .filter(edition_id=7001, source_row_id__in=sorted(required))
                .values_list('source_row_id', 'source_id', 'parent__source_row_id',
                             'parent__edition_id', 'parent__source_id', 'depth')) if required else ()
        except (CatalogReadError, DatabaseError):
            raise c.ContractError('reference: catalog_unavailable') from None
        conflicting = _catalog_projection_conflicts(projection)
        plans = _plan(parsed, tuple(catalog_rows), conflicting_source_rows=conflicting)
        flat = [ref for item in plans for ref in item.references]
        changed = []
        for reference, plan in zip(references, flat, strict=True):
            values = plan.derived_values()
            if any(getattr(reference, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(reference, key, value)
                changed.append(reference)
        if changed:
            IntakeReference.objects.using(using).bulk_update(changed,
                ['reference_status', 'verification_results', 'verified_identity', 'citation_text'], batch_size=100)
        return BatchReferenceVerification(batch.pk, parsed.payload_sha256, plans)
