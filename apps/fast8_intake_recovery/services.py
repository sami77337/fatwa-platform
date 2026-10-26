"""Select recovery evidence without reparsing, repairing or submitting records."""

import json
from dataclasses import dataclass

from apps.editorial_workbench.batch_fixtures import synthetic_inputs
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline.diagnostics import DiagnosticResult, diagnose_batches

BATCH_IDS = ("synthetic-csv", "synthetic-json", "synthetic-jsonl", "synthetic-malformed")


@dataclass(frozen=True, slots=True)
class RecoveryPreview:
    """Immutable output; callers receive detached dictionaries."""

    _json: bytes

    @property
    def report(self) -> dict:
        return json.loads(self._json)

    def json_bytes(self) -> bytes:
        return self._json

    @property
    def has_failures(self) -> bool:
        summary = self.report["summary"]
        return bool(summary["selected_failed_rows"] or summary["selected_failed_batches"])

    def preview_ar(self) -> str:
        report = self.report
        lines = [
            "معاينة تعافٍ لدفعات اصطناعية ثابتة — لم يُصحّح أو يُقبل أو يُعد إرسال أي سجل.",
            "التوصيات للمراجعة البشرية فقط؛ لم يُقدَّم جرد مصادر أو ربط موثوق.",
        ]
        for source in report["inputs"]:
            lines.append(f"الدفعة {source['batch_id']}؛ SHA256 {source['input_sha256']}")
        for failure in report["batch_failures"]:
            lines.append(
                f"{failure['batch_id']}: {failure['error_code']} — {failure['recovery_ar']}"
            )
            lines.append("تعذر تحديد الصفوف؛ لم يُخترع رقم صف أو مقطع بايتات.")
        for row in report["rows"]:
            lines.append(f"الدفعة {row['batch_id']}، الصف الأصلي {row['row']} — {row['state']}")
            lines.append(f"هوية البايتات: {row['row_id']}")
            for issue in row["recommendations"]:
                position = (
                    f"، الإحالة {issue['reference_index']}" if "reference_index" in issue else ""
                )
                lines.append(
                    f"  {issue['field']}{position}: {issue['code']} — {issue['recovery_ar']}"
                )
        for group in report["duplicate_groups"]:
            lines.append(f"مواضع مجموعة التكرار {group['group_id']}:")
            for location in group["locations"]:
                lines.append(f"  {location['batch_id']}، الصف الأصلي {location['row']}")
        lines.append(
            "Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; "
            "NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING"
        )
        return "\n".join(lines) + "\n"


def _project(
    diagnostic: DiagnosticResult,
    *,
    batch_id: str | None,
    row: int | None,
    failed_only: bool,
) -> RecoveryPreview:
    """Project a diagnostic snapshot; never run intake on the selected subset."""
    source = diagnostic.report
    inputs = [entry for entry in source["inputs"] if batch_id in (None, entry["batch_id"])]
    candidates = [entry for entry in source["rows"] if batch_id in (None, entry["batch_id"])]
    if row is not None:
        candidates = [entry for entry in candidates if entry["row"] == row]
        if not candidates:
            raise ValidationError("recovery: row_not_available")
    rows = []
    for entry in candidates:
        preparation = entry["preparation"]
        blocked = "blocked-invalid" in preparation["statuses"]
        if failed_only and not blocked:
            continue
        rows.append(
            dict(
                batch_id=entry["batch_id"],
                row=entry["row"],
                row_id=entry["row_id"],
                provenance=entry["provenance"],
                original=preparation["original"],
                csv_extra_cells=preparation.get("csv_extra_cells", []),
                upstream_statuses=preparation["statuses"],
                findings=preparation["findings"],
                state="BLOCKED_INVALID" if blocked else "MANUAL_REVIEW_REQUIRED",
                recommendations=entry["diagnostics"],
            )
        )
    groups = {
        issue["group_id"]
        for entry in rows
        for issue in entry["recommendations"]
        if "group_id" in issue
    }
    failures = [
        dict(
            batch_id=entry["batch_id"],
            input_sha256=entry["input_sha256"],
            error_code=entry["error_code"],
            recovery_ar=entry["recovery_ar"],
            row=None,
            state="ROWS_NOT_AVAILABLE",
        )
        for entry in inputs
        if entry["error_code"] is not None
    ]
    report = dict(
        schema="fatwa.fast8-intake-recovery.preview.v1",
        synthetic_only=True,
        preview_only=True,
        source_modification_performed=False,
        resubmission_performed=False,
        accepted_record_count=0,
        source_inventory="NOT_SUPPLIED",
        reference_mapping="NOT_CONNECTED",
        gates=source["gates"],
        phase01=source["phase01"],
        scope=source["scope"],
        deployment=source["deployment"],
        policy_acceptance={"U03": "OWNER_APPROVAL_PENDING", "U10": "OWNER_APPROVAL_PENDING"},
        selection=dict(batch_id=batch_id, row=row, failed_only=failed_only),
        collection_inputs=[
            dict(batch_id=entry["batch_id"], input_sha256=entry["input_sha256"])
            for entry in source["inputs"]
        ],
        summary=dict(
            collection_rows=source["summary"]["record_count"],
            collection_failed_rows=source["summary"]["status_counts"]["blocked-invalid"],
            collection_failed_batches=source["summary"]["error_count"],
            selected_rows=len(rows),
            selected_failed_rows=sum(entry["state"] == "BLOCKED_INVALID" for entry in rows),
            selected_failed_batches=len(failures),
        ),
        inputs=inputs,
        batch_failures=failures,
        rows=rows,
        duplicate_groups=[
            group for group in source["duplicate_groups"] if group["group_id"] in groups
        ],
    )
    return RecoveryPreview(
        (
            json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    )


def preview_recovery(
    *, batch_id: str | None = None, row: int | None = None, failed_only: bool = False
) -> RecoveryPreview:
    """Only exact fixed batch identifiers; no paths, payloads, inventory or mappings.

    Always diagnose the whole existing collection first so a selected duplicate
    remains blocked even when its other occurrence belongs to a different batch.
    """
    if batch_id is not None and (type(batch_id) is not str or batch_id not in BATCH_IDS):
        raise ValidationError("recovery: unknown_batch")
    if row is not None and (type(row) is not int or not 1 <= row <= 1000 or batch_id is None):
        raise ValidationError("recovery: batch_and_positive_row_required")
    if type(failed_only) is not bool:
        raise ValidationError("recovery: boolean_filter_required")
    if row is not None and failed_only:
        raise ValidationError("recovery: row_and_filter_are_exclusive")
    inputs = synthetic_inputs()
    if tuple(entry.batch_id for entry in inputs) != BATCH_IDS:
        raise ValidationError("recovery: fixture_contract_changed")
    diagnostic = diagnose_batches(inputs, synthetic_fixtures_only=True)
    return _project(diagnostic, batch_id=batch_id, row=row, failed_only=failed_only)
