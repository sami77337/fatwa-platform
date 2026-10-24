"""Synthetic, process-local prepared intake orchestration. No persistence or I/O."""

import csv
import hashlib
import json
from collections import Counter
from copy import copy
from dataclasses import asdict, dataclass
from typing import Mapping

from apps.fatwa_drafts.domain import DraftRecord, create_draft
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink, ValidationError, clip_url, text
from apps.reference_links.resolution import MAX_ID, ReadOnlyCatalog, resolve
from tools.content_intake.cli import (
    MAX_BYTES,
    MAX_REFERENCES,
    MAX_ROWS,
    SCHEMA,
    load,
    normalize,
    parse_json,
)


@dataclass(frozen=True, slots=True)
class C1Pointer:
    source_id: str
    heading_id: str

    def __post_init__(self):
        for value in (self.source_id, self.heading_id):
            text(value, "mapping.pointer", limit=100)
            if value != value.strip():
                raise ValidationError("mapping.pointer: whitespace")


@dataclass(frozen=True, slots=True)
class ExplicitMapping:
    """Caller asserts a separately tested conversion; test_identity is provenance, not proof."""

    c2: ReferenceLink
    edition_id: int
    source_row_id: int
    test_identity: str

    def __post_init__(self):
        if not isinstance(self.c2, ReferenceLink):
            raise ValidationError("mapping: C2_reference_required")
        if any(
            type(v) is not int or not 1 <= v <= MAX_ID
            for v in (self.edition_id, self.source_row_id)
        ):
            raise ValidationError("mapping: positive_integer_required")
        text(self.test_identity, "mapping.test_identity", limit=500)


@dataclass(frozen=True)
class Batch:
    report: dict
    drafts: tuple[DraftRecord, ...]

    def workbench_summary(self) -> dict:
        """Project receipt eligibility and reference verification independently."""
        items = self.report["items"]
        findings = Counter(f["code"] for row in items for f in row["findings"])
        references = Counter(ref["outcome"] for row in items for ref in row["references"])
        rows = []
        for row in items:
            source = row["original"]

            def reasons(severity):
                return [
                    {k: v for k, v in f.items() if k != "severity"}
                    for f in row["findings"]
                    if f["severity"] == severity
                ]

            rows.append(
                dict(
                    row=row["row"],
                    external_id=source.get("external_id")
                    if isinstance(source, dict) and isinstance(source.get("external_id"), str)
                    else None,
                    statuses=list(row["statuses"]),
                    draft_created=row["draft"] is not None,
                    rejection_reasons=reasons("error"),
                    review_reasons=reasons("review"),
                    reference_review_required="references-unverified" in row["statuses"],
                    reference_reasons=[
                        dict(
                            reference_index=ref.get("reference_index", i),
                            outcome=ref["outcome"],
                            reasons=list(ref["reasons"]),
                        )
                        for i, ref in enumerate(row["references"], 1)
                        if ref["outcome"] != "verified"
                    ],
                )
            )
        return dict(
            record_count=len(items),
            draft_count=sum(r["draft"] is not None for r in items),
            status_counts=_status_summary(items),
            finding_counts=dict(sorted(findings.items())),
            reference_counts=dict(sorted(references.items())),
            rows=rows,
        )

    def json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def preview_ar(self) -> str:
        lines = [
            "معاينة تجريبية محلية — مسودات غير منشورة؛ لم يحدث تحرير بشري.",
            "الإحالات تخص عناوين فهرس، ولا تثبت صلة السؤال أو صحة حكم.",
        ]
        for row in self.report["items"]:
            lines.append(f"السجل {row['row']}: {', '.join(row['statuses'])}")
            source = row["original"]
            if isinstance(source, dict):
                lines.append(
                    "السؤال الأصلي: " + str(source.get("question", source.get("title", "")))
                )
                lines.append(
                    "رابط المقطع المنجز: " + str(source.get("prepared_clip_url", "غير متوفر"))
                )
            for issue in row["findings"]:
                label = "سبب الرفض" if issue["severity"] == "error" else "يتطلب المراجعة"
                lines.append(f"{label}: {issue['field']} — {issue['code']}")
            for index, reference in enumerate(row["references"], 1):
                if reference["outcome"] != "verified":
                    position = reference.get("reference_index", index)
                    lines.append(
                        f"الإحالة {position}: {reference['outcome']} — {', '.join(reference['reasons'])}"
                    )
        return "\n".join(lines)


def _status_summary(items):
    return {
        status: sum(status in row["statuses"] for row in items)
        for status in (
            "ready-for-editor",
            "blocked-invalid",
            "needs-editor-review",
            "references-unverified",
        )
    }


def prepare_file(
    raw: bytes,
    suffix: str,
    *,
    synthetic_fixtures_only: bool = False,
    reference_map: Mapping[C1Pointer, ExplicitMapping] | None = None,
    catalog: ReadOnlyCatalog | None = None,
) -> Batch:
    """Prepare bounded CSV, JSON array/envelope or JSONL without dropping rejected rows.

    A UTF-8 BOM is accepted by the existing adapters. Input bytes are hashed before
    parsing; text is never trimmed, normalized or fetched. CSV reference JSON cells
    are decoded only for validation/matching while their originals remain visible.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError("pipeline: synthetic_fixture_acknowledgement_required")
    if not isinstance(suffix, str) or suffix.lower() not in {".csv", ".json", ".jsonl"}:
        raise ValidationError("input: unsupported_format")
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValidationError("input: invalid_size_or_type")
    try:
        rows = load(raw, suffix.lower())
    except (ValueError, UnicodeError, csv.Error, RecursionError) as exc:
        raise ValidationError("input: malformed_or_over_limit") from exc
    if not 1 <= len(rows) <= MAX_ROWS:
        raise ValidationError("items: expected_1_to_1000")
    return _prepare_rows(
        raw, rows, input_format=suffix.lower(), reference_map=reference_map, catalog=catalog
    )


def prepare_batch(
    raw: bytes,
    *,
    synthetic_fixtures_only: bool = False,
    reference_map: Mapping[C1Pointer, ExplicitMapping] | None = None,
    catalog: ReadOnlyCatalog | None = None,
) -> Batch:
    """Accept only C1 JSON envelope, max 1 MB/1000 rows/100 links per row.

    Caller must supply only synthetic data. Returned content stays in caller memory.
    Mapping and catalog are trusted dependencies, never constructed from payload.
    Malformed envelopes raise ValidationError; row errors remain structured findings.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError("pipeline: synthetic_fixture_acknowledgement_required")
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValidationError("json: invalid_size_or_type")
    try:
        envelope = parse_json(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValidationError("json: invalid_utf8_or_json") from exc
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"schema", "items"}
        or envelope["schema"] != SCHEMA
    ):
        raise ValidationError("envelope: invalid")
    rows = envelope["items"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValidationError("items: expected_1_to_1000")
    # Reject escaped lone surrogates even in rejected rows, before producing UTF-8 reports.
    try:
        json.dumps(envelope, ensure_ascii=False).encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValidationError("json: invalid_utf8") from exc
    return _prepare_rows(
        raw, rows, input_format=".json", reference_map=reference_map, catalog=catalog
    )


def _prepare_rows(raw, rows, *, input_format, reference_map, catalog):
    mappings = dict(reference_map or {})
    if any(
        not isinstance(k, C1Pointer) or not isinstance(v, ExplicitMapping)
        for k, v in mappings.items()
    ):
        raise ValidationError("mapping: typed_entries_required")
    ids = Counter(
        r["external_id"]
        for r in rows
        if isinstance(r, dict) and isinstance(r.get("external_id"), str)
    )
    duplicates = {value for value, count in ids.items() if count > 1}
    reports, drafts = [], []
    for number, source in enumerate(rows, 1):
        findings, references, refs = [], [], []

        def finding(field, code, severity="error", reference_index=None):
            issue = dict(field=field, code=code, severity=severity)
            if reference_index is not None:
                issue["reference_index"] = reference_index
            if issue not in findings:
                findings.append(issue)

        links = source.get("reference_links", []) if isinstance(source, dict) else []
        if (
            (
                not isinstance(links, list)
                and not (input_format == ".csv" and isinstance(links, str))
            )
            or isinstance(links, list)
            and len(links) > MAX_REFERENCES
        ):
            # Canonical D1 links must be actual bounded lists. Reject before C1
            # parses a CSV-style string or traverses an oversized reference list.
            finding("reference_links", "expected_list_at_most_100")
            # Check all independent fields without traversing oversized links.
            validation_source = copy(source)
            validation_source["reference_links"] = []
        else:
            validation_source = source
        normalized, c1_findings = normalize([validation_source])
        findings.extend({k: v for k, v in f.items() if k != "row"} for f in c1_findings)
        if isinstance(source, dict):
            if isinstance(source.get("external_id"), str) and source["external_id"] in duplicates:
                finding("external_id", "duplicate_id")
            # C2 enforces a stricter media contract than the C1 file adapter.
            # Run it even when another field or reference already rejected the row.
            clip = source.get("prepared_clip_url", "")
            if (
                isinstance(clip, str)
                and clip
                and not any(
                    f["field"] == "prepared_clip_url" and f["severity"] == "error" for f in findings
                )
            ):
                try:
                    clip_url(clip)
                except ValidationError as exc:
                    finding("prepared_clip_url", str(exc).partition(": ")[2])
            if normalized:
                seen, mapped_seen = set(), set()
                for index, link in enumerate(normalized[0]["reference_links"], 1):
                    try:
                        pointer = C1Pointer(**link)
                    except ValidationError:
                        finding("reference_links", "invalid_pointer", reference_index=index)
                        continue
                    if pointer in seen:
                        finding("reference_links", "duplicate_reference", reference_index=index)
                    seen.add(pointer)
                    mapped = mappings.get(pointer)
                    result = {
                        "original": link,
                        "reference_index": index,
                        "outcome": "unverified",
                        "reasons": [],
                    }
                    if mapped is None:
                        finding("reference_links", "needs_mapping", "review", reference_index=index)
                        result["reasons"] = ["unsupported_C1_identity_needs_mapping"]
                    else:
                        if mapped.c2 in mapped_seen:
                            finding(
                                "reference_links",
                                "duplicate_mapped_reference",
                                reference_index=index,
                            )
                        mapped_seen.add(mapped.c2)
                        refs.append(mapped.c2)
                        result["mapping"] = asdict(mapped)
                        if catalog is None:
                            result["reasons"] = ["trusted_catalog_not_supplied"]
                        else:
                            resolution = resolve(
                                {
                                    "edition_id": mapped.edition_id,
                                    "source_row_id": mapped.source_row_id,
                                },
                                catalog,
                            )
                            result.update(resolution.internal_payload())
                            result["resolver_outcome"] = resolution.outcome.value
                            if resolution.evidence is not None and (
                                any(
                                    getattr(resolution.evidence, key) != getattr(mapped.c2, key)
                                    for key in (
                                        "source_namespace",
                                        "source_book_id",
                                        "source_input_sha256",
                                    )
                                )
                                or any(
                                    getattr(resolution.evidence, key) is not None
                                    and getattr(resolution.evidence, key) != getattr(mapped.c2, key)
                                    for key in ("edition_key", "source_archive_sha256")
                                )
                            ):
                                result.update(
                                    outcome="mismatched", reasons=["C2_source_identity_mismatch"]
                                )
                            elif result["outcome"] == "mismatched_metadata":
                                result["outcome"] = "mismatched"
                    references.append(result)
        record = None
        if normalized and not any(f["severity"] == "error" for f in findings):
            # Preserve exact source strings; C1 normalization is validation only.
            question = source.get("question", source.get("title", ""))
            clip = source.get("prepared_clip_url", "")
            try:
                text(source["external_id"], "external_id", limit=100)
                text(question, "question")
                text(source.get("staff_notes", ""), "staff_notes", required=False)
                if clip:
                    item = IntakeItem(
                        source["external_id"],
                        question,
                        clip,
                        source.get("staff_notes", ""),
                        tuple(refs),
                    )
                    record = create_draft(
                        item,
                        human_editor="synthetic-pipeline-receipt",
                        editorial_note="Automated receipt only; no human editing performed.",
                    )
            except ValidationError as exc:
                field, _, code = str(exc).partition(": ")
                finding(field, code)
        blocked = any(f["severity"] == "error" for f in findings)
        if blocked:
            record = None
        statuses = [
            "blocked-invalid"
            if blocked
            else "needs-editor-review"
            if any(f["severity"] == "review" for f in findings)
            else "ready-for-editor"
        ]
        if not references or any(r["outcome"] != "verified" for r in references):
            statuses.append("references-unverified")
        if record is not None:
            drafts.append(record)
        original = source
        if input_format == ".csv" and isinstance(source, dict) and None in source:
            # CSV overflow cells have no column name. Preserve them separately
            # instead of emitting a non-string JSON object key in the original.
            original = {key: value for key, value in source.items() if key is not None}
        reports.append(
            dict(
                row=number,
                original=original,
                findings=findings,
                statuses=statuses,
                references=references,
                draft=asdict(record) if record else None,
            )
        )
        if original is not source:
            reports[-1]["csv_extra_cells"] = list(source[None])
    batch = Batch(
        dict(
            schema="fatwa.prepared-pipeline.report.v1",
            input_sha256=hashlib.sha256(raw).hexdigest(),
            input_format=input_format,
            gates={"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"},
            synthetic_only=True,
            human_editing_performed=False,
            summary=_status_summary(reports),
            items=reports,
        ),
        tuple(drafts),
    )
    batch.report["workbench"] = batch.workbench_summary()
    return batch
