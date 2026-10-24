"""Read-only presentation adapters for fixed, invented editorial fixtures.

No persistence, source discovery, media fetching or editorial state transitions.
Wave7 catalog rows below are explicit assertions matching its fixed fixture seed;
they establish a technical TOC match only, never an inspected owner archive.
"""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
from apps.fatwa_drafts.domain import DraftRecord
from apps.fatwa_drafts.intake import ValidationError, serialize_intake
from apps.intake_workflow import contracts as c
from apps.intake_workflow import fixtures
from apps.intake_workflow.intake import check_intake
from apps.prepared_pipeline import prepare_batch
from apps.reference_links.diagnostics import build_reference_diagnostics
from apps.reference_links.resolution import Heading, SnapshotCatalog


class WorkbenchDataError(ValueError):
    """Expected invalid synthetic adapter data; programming/system errors propagate."""


@dataclass(frozen=True, slots=True)
class WorkbenchCase:
    key: str
    external_id: str | None
    question: str | None
    prepared_clip_url: str | None
    raw_source: str
    source_start: int | None
    source_end: int | None
    payload_sha256: str
    fixture_label: str
    status: str
    status_label: str
    issues: tuple[str, ...]
    record: DraftRecord | None
    references: tuple[dict, ...]


_STATUS_LABELS = {
    "ready": "جاهز للعرض التحريري المحلي",
    "review": "يحتاج مراجعة بشرية",
    "blocked": "سجل مرفوض؛ لا توجد مسودة",
}


def _asserted_catalog() -> tuple[Heading, ...]:
    """Fixed synthetic seed assertions, independent of incoming row contents."""
    root = "كِتَابٌ اصطناعي"
    return tuple(
        Heading(
            7001,
            row,
            "مرجع اصطناعي لتجارب Wave7",
            title,
            "الأول",
            page,
            (root,) if row == 1 else (root, title),
            "wave7-synthetic-toc",
            "622",
            "b" * 64,
            "wave7-synthetic-edition-v1",
            "a" * 64,
        )
        for row, title, page in (
            (1, root, 7),
            (2, "بابٌ اصطناعي أول", 8),
            (3, "بابٌ اصطناعي ثان", 9),
        )
    )


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WorkbenchDataError(code)


def _text_field(original: object, name: str) -> str | None:
    value = original.get(name) if isinstance(original, dict) else None
    return value if isinstance(value, str) else None


def _history_case() -> WorkbenchCase:
    record = REVISION_HISTORY_RECORD
    # This is serialization of an existing IntakeItem, never an original file
    # slice. Retain the exact source and Revision objects rather than rebuilding.
    serialized = serialize_intake((record.intake,))
    explanation = "هوية إحالة اصطناعية لسجل المراجعات؛ لا يوجد لها ربط في لقطة فهرس Wave7 الثابتة."
    references = []
    for ordinal, reference in enumerate(record.current.reference_links, 1):
        identity = asdict(reference)
        text = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        references.append(
            {
                "reference_ordinal": ordinal,
                "status": "unresolved",
                "contract_status": c.ReferenceStatus.UNVERIFIED.value,
                "original_identity": identity,
                "source": {"text": text, "start": None, "end": None},
                "source_sha256": sha256(text.encode("utf-8")).hexdigest(),
                "source_kind": "serialized_revision_reference",
                "reasons": ["no_fixed_wave7_binding_for_revision_identity"],
                "explanation_ar": explanation,
                "reason_explanations_ar": [explanation],
                "verification_limit_ar": "لا تثبت هذه النتيجة صحة علمية أو ملاءمة إحالة، ولا تعني فحص الأرشيف.",
                "verified_identity": {},
                "evidence": None,
            }
        )
    return WorkbenchCase(
        key="history",
        external_id=record.intake.external_id,
        question=record.intake.question,
        prepared_clip_url=record.intake.prepared_clip_url,
        raw_source=serialized.decode("utf-8"),
        source_start=None,
        source_end=None,
        payload_sha256=sha256(serialized).hexdigest(),
        fixture_label="سجل مراجعات اصطناعي ثابت؛ تسلسل JSON للاستلام الأصلي، وليس شريحة من ملف مصدر",
        status="review",
        status_label=_STATUS_LABELS["review"],
        issues=(explanation,),
        record=record,
        references=tuple(references),
    )


def _intake_cases() -> tuple[WorkbenchCase, ...]:
    raw = fixtures.synthetic_payload()
    # check_intake reuses c.parse_synthetic_payload and the existing Wave7 row
    # checks, including stricter IDs. Its exact original slices remain authority.
    checked = check_intake(raw, synthetic_fixtures_only=True)
    parsed = checked.parsed
    catalog_rows = _asserted_catalog()
    # Explicit schema conversion reuses the original JSON items array verbatim;
    # no question normalization or external-ID keyed association is involved.
    prepared_raw = parsed.prepared_bytes()
    batch = prepare_batch(
        prepared_raw,
        synthetic_fixtures_only=True,
        reference_map=fixtures.trusted_reference_map(),
        catalog=SnapshotCatalog(catalog_rows),
    )
    diagnostic = build_reference_diagnostics(
        raw, synthetic_fixtures_only=True, catalog_rows=catalog_rows
    ).to_payload()
    reports = batch.report.get("items")
    reference_items = diagnostic.get("items")
    _require(
        isinstance(reports, list) and isinstance(reference_items, list),
        "workbench: invalid_service_report",
    )
    _require(
        len(reports) == len(parsed.items) == len(checked.items) == len(reference_items),
        "workbench: service_row_alignment_mismatch",
    )
    _require(
        batch.report.get("input_sha256") == sha256(prepared_raw).hexdigest()
        and diagnostic.get("input_sha256") == parsed.payload_sha256
        and batch.report.get("synthetic_only") is True
        and batch.report.get("human_editing_performed") is False,
        "workbench: service_provenance_mismatch",
    )
    cases = []
    draft_position = 0
    for ordinal, (original, source, item, report, reference_item) in enumerate(
        zip(
            parsed.items, parsed.item_sources, checked.items, reports, reference_items, strict=True
        ),
        1,
    ):
        _require(
            isinstance(report, dict) and isinstance(reference_item, dict),
            "workbench: invalid_service_row",
        )
        _require(
            report.get("row") == ordinal
            and report.get("original") == original
            and item.row_ordinal == ordinal
            and item.source == source
            and reference_item.get("row_ordinal") == ordinal
            and reference_item.get("source") == asdict(source),
            "workbench: service_source_alignment_mismatch",
        )
        _require(
            "draft" in report
            and isinstance(report.get("statuses"), list)
            and isinstance(reference_item.get("references"), list),
            "workbench: invalid_service_row",
        )
        record = None
        if report["draft"] is not None:
            _require(draft_position < len(batch.drafts), "workbench: missing_row_draft")
            record = batch.drafts[draft_position]
            draft_position += 1
            _require(
                isinstance(record, DraftRecord) and asdict(record) == report["draft"],
                "workbench: draft_row_alignment_mismatch",
            )
            _require(
                record.intake.external_id == _text_field(original, "external_id")
                and record.intake.question == _text_field(original, "question")
                and record.intake.prepared_clip_url == _text_field(original, "prepared_clip_url")
                and len(record.history) == 1
                and record.current.action == "received"
                and record.current.title == ""
                and record.current.answer == "",
                "workbench: draft_source_identity_mismatch",
            )
        blocked = item.intake_status == c.IntakeStatus.BLOCKED_INVALID.value
        _require(
            not ("blocked-invalid" in report["statuses"] and record is not None),
            "workbench: blocked_pipeline_draft",
        )
        if blocked:
            record = None
        references = tuple(reference_item["references"])
        issues = [
            f"بيانات الاستلام: {finding['field']} ({finding['code']})."
            for finding in item.validation_results["findings"]
        ]
        if not _text_field(original, "prepared_clip_url"):
            issues.append("رابط المقطع الجاهز غير مرفق؛ لا توجد مسودة قابلة للتحرير.")
        if not references:
            issues.append("لا توجد إحالات مرجعية مرفقة.")
        if any(reference["status"] != "verified" for reference in references):
            issues.append("توجد إحالات غير محسومة أو متعارضة؛ يلزم فحص بشري.")
        status = (
            "blocked"
            if blocked
            else "review"
            if record is None
            or issues
            or item.intake_status != c.IntakeStatus.READY_FOR_EDITOR.value
            else "ready"
        )
        cases.append(
            WorkbenchCase(
                key=f"intake-{ordinal}",
                external_id=_text_field(original, "external_id"),
                question=_text_field(original, "question"),
                prepared_clip_url=_text_field(original, "prepared_clip_url"),
                raw_source=source.text,
                source_start=source.start,
                source_end=source.end,
                payload_sha256=parsed.payload_sha256,
                fixture_label=f"دفعة Wave7 الاصطناعية الثابتة؛ شريحة الصف الأصلي {ordinal} بالبايت",
                status=status,
                status_label=_STATUS_LABELS[status],
                issues=tuple(dict.fromkeys(issues)),
                record=record,
                references=references,
            )
        )
    _require(draft_position == len(batch.drafts), "workbench: extra_unassigned_draft")
    return tuple(cases)


def build_cases() -> tuple[WorkbenchCase, ...]:
    """Fresh local fixture adapters only; no caller payload/path or shared stage."""
    try:
        return (_history_case(), *_intake_cases())
    except (c.ContractError, ValidationError) as exc:
        raise WorkbenchDataError("workbench: invalid_fixed_synthetic_data") from exc


def build_prepared_workbench():
    """Compose only the built-in synthetic batches; no caller path or payload."""
    from .batches import build_prepared_workbench as build

    try:
        return build()
    except ValidationError as exc:
        raise WorkbenchDataError("workbench: invalid_fixed_prepared_data") from exc
