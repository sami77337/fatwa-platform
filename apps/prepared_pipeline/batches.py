"""Bounded, process-local orchestration of acknowledged synthetic input files."""

import hashlib
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from apps.fatwa_drafts.intake import ValidationError
from apps.reference_links.resolution import ReadOnlyCatalog
from tools.content_intake.cli import MAX_BYTES, MAX_ROWS

from . import Batch, C1Pointer, ExplicitMapping


@dataclass(frozen=True, slots=True)
class PreparedInput:
    batch_id: str
    raw: bytes
    suffix: str

    def __post_init__(self):
        identity = self.batch_id
        if (
            not isinstance(identity, str)
            or not identity
            or len(identity) > 100
            or identity != identity.strip()
            or any(unicodedata.category(c).startswith("C") for c in identity)
        ):
            raise ValidationError("batch_id: invalid_identity")
        if not isinstance(self.raw, bytes):
            raise ValidationError("input: invalid_size_or_type")
        if self.suffix not in (".csv", ".json", ".jsonl"):
            raise ValidationError("input: unsupported_format")


@dataclass(frozen=True, slots=True)
class PreparedBatch:
    batch_id: str
    input_sha256: str | None
    input_format: str
    batch: Batch | None = None
    error_code: str | None = None

    def report(self) -> dict:
        if self.batch is None:
            status = "ERROR"
        elif self.batch.report["summary"]["blocked-invalid"]:
            status = "BLOCKED"
        elif self.batch.report["summary"]["needs-editor-review"]:
            status = "REVIEW_REQUIRED"
        else:
            status = "READY"
        return dict(
            batch_id=self.batch_id,
            input_sha256=self.input_sha256,
            input_format=self.input_format,
            status=status,
            error_code=self.error_code,
            report=self.batch.report if self.batch is not None else None,
        )


@dataclass(frozen=True, slots=True)
class BatchCollection:
    batches: tuple[PreparedBatch, ...]

    @property
    def has_errors(self) -> bool:
        return any(
            entry.batch is None or entry.batch.report["summary"]["blocked-invalid"]
            for entry in self.batches
        )

    def workbench_summary(self) -> dict:
        statuses, findings, references = Counter(), Counter(), Counter()
        rows, draft_count = [], 0
        for entry in self.batches:
            if entry.batch is None:
                continue
            summary = entry.batch.workbench_summary()
            statuses.update(summary["status_counts"])
            findings.update(summary["finding_counts"])
            references.update(summary["reference_counts"])
            draft_count += summary["draft_count"]
            rows.extend(dict(row, batch_id=entry.batch_id) for row in summary["rows"])
        return dict(
            batch_count=len(self.batches),
            error_count=sum(entry.batch is None for entry in self.batches),
            record_count=len(rows),
            draft_count=draft_count,
            status_counts=dict(statuses),
            finding_counts=dict(findings),
            reference_counts=dict(references),
            rows=rows,
        )

    @property
    def report(self) -> dict:
        return dict(
            schema="fatwa.prepared-pipeline.collection.v1",
            synthetic_only=True,
            human_editing_performed=False,
            gates={"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"},
            summary=self.workbench_summary(),
            batches=[entry.report() for entry in self.batches],
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


def prepare_batches(
    inputs: Iterable[PreparedInput],
    *,
    synthetic_fixtures_only: bool = False,
    reference_map: Mapping[C1Pointer, ExplicitMapping] | None = None,
    catalog: ReadOnlyCatalog | None = None,
) -> BatchCollection:
    """Isolate malformed files; collection limits and descriptor errors fail closed.

    The 1 MB and 1000 record limits apply across all files together. Input IDs
    identify exact caller-selected files; no mappings can come from file payloads.
    """
    if synthetic_fixtures_only is not True:
        raise ValidationError("pipeline: synthetic_fixture_acknowledgement_required")
    sources, seen, byte_count = [], set(), 0
    for item in inputs:
        if not isinstance(item, PreparedInput):
            raise ValidationError("collection: prepared_inputs_required")
        if len(sources) >= MAX_ROWS:
            raise ValidationError("collection: expected_at_most_1000_inputs")
        if item.batch_id in seen:
            raise ValidationError("batch_id: duplicate_id")
        seen.add(item.batch_id)
        byte_count += len(item.raw)
        if byte_count > MAX_BYTES:
            raise ValidationError("collection: input_byte_limit_exceeded")
        sources.append(item)

    # Resolve the shared implementation lazily to avoid a package import cycle.
    from . import _status_summary, prepare_file

    entries, row_count = [], 0
    for item in sources:
        digest = hashlib.sha256(item.raw).hexdigest()
        try:
            batch = prepare_file(
                item.raw,
                item.suffix,
                synthetic_fixtures_only=True,
                reference_map=reference_map,
                catalog=catalog,
            )
        except ValidationError:
            entries.append(
                PreparedBatch(item.batch_id, digest, item.suffix, error_code="MALFORMED_INPUT")
            )
            continue
        row_count += len(batch.report["items"])
        if row_count > MAX_ROWS:
            raise ValidationError("collection: record_limit_exceeded")
        entries.append(PreparedBatch(item.batch_id, digest, item.suffix, batch))

    locations: dict[str, set[int]] = {}
    for index, entry in enumerate(entries):
        if entry.batch is None:
            continue
        for item in entry.batch.report["items"]:
            original = item["original"]
            identity = original.get("external_id") if isinstance(original, dict) else None
            if isinstance(identity, str):
                locations.setdefault(identity, set()).add(index)
    duplicates = {identity for identity, indexes in locations.items() if len(indexes) > 1}
    if duplicates:
        for index, entry in enumerate(entries):
            if entry.batch is None:
                continue
            reports = []
            for item in entry.batch.report["items"]:
                original = item["original"]
                identity = original.get("external_id") if isinstance(original, dict) else None
                if isinstance(identity, str) and identity in duplicates:
                    findings = list(item["findings"])
                    if not any(
                        f["field"] == "external_id" and f["code"] == "duplicate_id"
                        for f in findings
                    ):
                        findings.append(
                            dict(field="external_id", code="duplicate_id", severity="error")
                        )
                    statuses = ["blocked-invalid"]
                    if "references-unverified" in item["statuses"]:
                        statuses.append("references-unverified")
                    item = dict(item, findings=findings, statuses=statuses, draft=None)
                reports.append(item)
            drafts = tuple(
                draft for draft in entry.batch.drafts if draft.intake.external_id not in duplicates
            )
            batch = Batch(
                dict(entry.batch.report, items=reports, summary=_status_summary(reports)), drafts
            )
            batch.report["workbench"] = batch.workbench_summary()
            entries[index] = PreparedBatch(
                entry.batch_id, entry.input_sha256, entry.input_format, batch
            )
    return BatchCollection(tuple(entries))
