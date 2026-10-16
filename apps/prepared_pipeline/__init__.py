"""Synthetic, process-local prepared intake orchestration. No persistence or I/O."""
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Mapping

from tools.content_intake.cli import SCHEMA, normalize, parse_json
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink, ValidationError, text
from apps.fatwa_drafts.domain import DraftRecord, create_draft
from apps.reference_links.resolution import ReadOnlyCatalog, resolve, MAX_ID


@dataclass(frozen=True, slots=True)
class C1Pointer:
    source_id: str
    heading_id: str

    def __post_init__(self):
        for value in (self.source_id, self.heading_id):
            text(value, 'mapping.pointer', limit=100)
            if value != value.strip():
                raise ValidationError('mapping.pointer: whitespace')


@dataclass(frozen=True, slots=True)
class ExplicitMapping:
    """Caller asserts a separately tested conversion; test_identity is provenance, not proof."""
    c2: ReferenceLink
    edition_id: int
    source_row_id: int
    test_identity: str

    def __post_init__(self):
        if not isinstance(self.c2, ReferenceLink):
            raise ValidationError('mapping: C2_reference_required')
        if any(type(v) is not int or not 1 <= v <= MAX_ID
               for v in (self.edition_id, self.source_row_id)):
            raise ValidationError('mapping: positive_integer_required')
        text(self.test_identity, 'mapping.test_identity', limit=500)


@dataclass(frozen=True)
class Batch:
    report: dict
    drafts: tuple[DraftRecord, ...]

    def json_bytes(self) -> bytes:
        return (json.dumps(self.report, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')

    def preview_ar(self) -> str:
        lines = ['معاينة تجريبية محلية — مسودات غير منشورة؛ لم يحدث تحرير بشري.',
                 'الإحالات تخص عناوين فهرس، ولا تثبت صلة السؤال أو صحة حكم.']
        for row in self.report['items']:
            lines.append(f"السجل {row['row']}: {', '.join(row['statuses'])}")
            source = row['original']
            if isinstance(source, dict):
                lines.append('السؤال الأصلي: ' + str(source.get('question', source.get('title', ''))))
                lines.append('رابط المقطع المنجز: ' + str(source.get('prepared_clip_url', 'غير متوفر')))
        return '\n'.join(lines)


def prepare_batch(raw: bytes, *, synthetic_fixtures_only: bool = False,
                  reference_map: Mapping[C1Pointer, ExplicitMapping] | None = None,
                  catalog: ReadOnlyCatalog | None = None) -> Batch:
    """Accept only C1 JSON envelope, max 1 MB/1000 rows/100 links per row.

    Caller must supply only synthetic data. Returned content stays in caller memory.
    Mapping and catalog are trusted dependencies, never constructed from payload.
    Malformed envelopes raise ValidationError; row errors remain structured findings.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError('pipeline: synthetic_fixture_acknowledgement_required')
    if not isinstance(raw, bytes) or len(raw) > 1_000_000:
        raise ValidationError('json: invalid_size_or_type')
    try:
        envelope = parse_json(raw.decode('utf-8', errors='strict'))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValidationError('json: invalid_utf8_or_json') from exc
    if (not isinstance(envelope, dict) or set(envelope) != {'schema', 'items'}
            or envelope['schema'] != SCHEMA):
        raise ValidationError('envelope: invalid')
    rows = envelope['items']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValidationError('items: expected_1_to_1000')
    # Reject escaped lone surrogates even in rejected rows, before producing UTF-8 reports.
    try:
        json.dumps(envelope, ensure_ascii=False).encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise ValidationError('json: invalid_utf8') from exc
    mappings = dict(reference_map or {})
    if any(not isinstance(k, C1Pointer) or not isinstance(v, ExplicitMapping)
           for k, v in mappings.items()):
        raise ValidationError('mapping: typed_entries_required')
    ids = [r.get('external_id') for r in rows if isinstance(r, dict)]
    duplicates = {v for v in ids if isinstance(v, str) and ids.count(v) > 1}
    reports, drafts = [], []
    for number, source in enumerate(rows, 1):
        findings, references, refs = [], [], []
        def finding(field, code, severity='error'):
            findings.append(dict(field=field, code=code, severity=severity))
        normalized, c1_findings = normalize([source])
        findings.extend({k: v for k, v in f.items() if k != 'row'} for f in c1_findings)
        if isinstance(source, dict):
            if isinstance(source.get('external_id'), str) and source['external_id'] in duplicates:
                finding('external_id', 'duplicate_id')
            links = source.get('reference_links', [])
            if not isinstance(links, list) or len(links) > 100:
                finding('reference_links', 'expected_list_at_most_100')
            elif normalized:
                seen = set()
                for link in normalized[0]['reference_links']:
                    try:
                        pointer = C1Pointer(**link)
                    except ValidationError:
                        finding('reference_links', 'invalid_pointer')
                        continue
                    if pointer in seen:
                        finding('reference_links', 'duplicate_reference')
                    seen.add(pointer)
                    mapped = mappings.get(pointer)
                    result = {'original': link, 'outcome': 'unverified', 'reasons': []}
                    if mapped is None:
                        finding('reference_links', 'needs_mapping', 'review')
                        result['reasons'] = ['unsupported_C1_identity_needs_mapping']
                    else:
                        refs.append(mapped.c2)
                        result['mapping'] = asdict(mapped)
                        if catalog is None:
                            result['reasons'] = ['trusted_catalog_not_supplied']
                        else:
                            resolution = resolve({'edition_id': mapped.edition_id,
                                                  'source_row_id': mapped.source_row_id}, catalog)
                            result.update(resolution.internal_payload())
                            result['resolver_outcome'] = resolution.outcome.value
                            if resolution.evidence is not None and any(
                                getattr(resolution.evidence, key) != getattr(mapped.c2, key)
                                for key in ('source_namespace', 'source_book_id', 'source_input_sha256')
                            ):
                                result.update(outcome='mismatched', reasons=['C2_source_identity_mismatch'])
                            elif result['outcome'] == 'mismatched_metadata':
                                result['outcome'] = 'mismatched'
                    references.append(result)
        record = None
        if normalized and not any(f['severity'] == 'error' for f in findings):
            # Preserve exact source strings; C1 normalization is validation only.
            question = source.get('question', source.get('title', ''))
            clip = source.get('prepared_clip_url', '')
            try:
                text(source['external_id'], 'external_id', limit=100)
                text(question, 'question')
                text(source.get('staff_notes', ''), 'staff_notes', required=False)
                if clip:
                    item = IntakeItem(source['external_id'], question, clip,
                                      source.get('staff_notes', ''), tuple(refs))
                    record = create_draft(item, human_editor='synthetic-pipeline-receipt',
                                          editorial_note='Automated receipt only; no human editing performed.')
            except ValidationError as exc:
                finding('C2', str(exc))
        blocked = any(f['severity'] == 'error' for f in findings)
        if blocked:
            record = None
        statuses = ['blocked-invalid' if blocked else 'needs-editor-review'
                    if any(f['severity'] == 'review' for f in findings) else 'ready-for-editor']
        if not references or any(r['outcome'] != 'verified' for r in references):
            statuses.append('references-unverified')
        if record is not None:
            drafts.append(record)
        reports.append(dict(row=number, original=source, findings=findings,
                            statuses=statuses, references=references,
                            draft=asdict(record) if record else None))
    return Batch(dict(schema='fatwa.prepared-pipeline.report.v1',
                      input_sha256=hashlib.sha256(raw).hexdigest(),
                      gates={'B': 'NOT_PASSED', 'C': 'HOLD', 'D': 'HOLD', 'E': 'HOLD'},
                      synthetic_only=True, human_editing_performed=False,
                      summary={status: sum(status in r['statuses'] for r in reports)
                               for status in ('ready-for-editor', 'blocked-invalid',
                                              'needs-editor-review', 'references-unverified')},
                      items=reports), tuple(drafts))
