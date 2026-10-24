"""Read-only bridge from PR95 preparation to PR96 record/history presentation."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.intake_workflow import fixtures
from apps.prepared_pipeline.batches import prepare_batches
from apps.reference_links.resolution import SnapshotCatalog
from tools.content_intake.cli import load

from .batch_fixtures import synthetic_inputs
from .services import WorkbenchCase, _asserted_catalog, _require, _text_field


@dataclass(frozen=True, slots=True)
class RecoveryReason:
    field: str
    code: str
    severity: str
    reference_index: int | None
    explanation: str
    recovery: str


@dataclass(frozen=True, slots=True)
class PreparedCase(WorkbenchCase):
    batch_id: str
    row_ordinal: int
    intake_state: str
    original: object
    csv_extra_cells: tuple[str, ...]
    reasons: tuple[RecoveryReason, ...]
    reference_review_required: bool


@dataclass(frozen=True, slots=True)
class BatchOverview:
    batch_id: str
    input_format: str
    input_sha256: str
    raw_source: str
    record_count: int
    valid_count: int
    rejected_count: int
    pending_count: int
    error_code: str | None
    recovery: str


@dataclass(frozen=True, slots=True)
class PreparedWorkbench:
    cases: tuple[PreparedCase, ...]
    batches: tuple[BatchOverview, ...]


def _reason(finding: dict) -> RecoveryReason:
    field, code = finding["field"], finding["code"]
    if code == "duplicate_id":
        explanation = "المعرّف مكرر داخل الدفعة أو عبر الدفعات؛ رُفضت جميع نسخه."
        recovery = "راجع هوية كل سجل في العينة الاصطناعية وأزل التكرار من مصدرها ثم أعد التحضير."
    elif field == "prepared_clip_url":
        explanation = "رابط المقطع مفقود أو لا يطابق ضوابط الاستلام."
        recovery = (
            "أصلح رابط HTTPS الاصطناعي في العينة المحلية ثم أعد التحضير؛ لا يُنزَّل أي مقطع هنا."
        )
    elif field == "reference_links":
        explanation = "بنية الإحالة أو هويتها تحتاج تصحيحًا أو ربطًا مرجعيًا مستقلًا."
        recovery = "راجع موضع المؤشر وهويته في العينة والربط الاصطناعي الموثوق؛ لا تستنتج استشهادًا أو اعتمادًا."
    else:
        explanation = "لم يستوف الحقل قواعد الاستلام الموضحة برمز السبب."
        recovery = "صحح الحقل أو بنية الصف في العينة الاصطناعية المحلية ثم أعد التحضير؛ يبقى الأصل الحالي ظاهرًا."
    return RecoveryReason(
        field, code, finding["severity"], finding.get("reference_index"), explanation, recovery
    )


def _references(original, reports, findings, suffix):
    links = original.get("reference_links", []) if isinstance(original, dict) else []
    if suffix == ".csv" and isinstance(links, str):
        try:
            links = json.loads(links)
        except ValueError:
            links = []
    if not isinstance(links, list):
        return ()
    indexed = {report["reference_index"]: report for report in reports}
    _require(len(indexed) == len(reports), "workbench: reference_position_mismatch")
    _require(
        all(1 <= index <= len(links) for index in indexed), "workbench: reference_position_mismatch"
    )
    results = []
    for index, pointer in enumerate(links, 1):
        report = indexed.get(index)
        if report:
            _require(report["original"] == pointer, "workbench: reference_identity_mismatch")
        status = report["outcome"] if report else "unverified"
        reasons = (
            list(report["reasons"])
            if report
            else [f["code"] for f in findings if f.get("reference_index") == index]
            or ["reference_not_resolved_for_rejected_row"]
        )
        verified = status == "verified"
        mapping = report.get("mapping", {}) if report else {}
        text = json.dumps(pointer, ensure_ascii=False, sort_keys=True)
        results.append(
            dict(
                reference_ordinal=index,
                status=status,
                contract_status=status,
                original_identity=pointer if isinstance(pointer, dict) else {},
                source={"text": text, "start": None, "end": None},
                reasons=reasons,
                explanation_ar="مطابقة تقنية مع فهرس اصطناعي ثابت."
                if verified
                else "إحالة غير متحققة؛ يلزم فحص مستقل.",
                reason_explanations_ar=[],
                verification_limit_ar="مطابقة عنوان اصطناعي فقط؛ لا تثبت صحة علمية أو ملاءمة استشهاد أو فحص أرشيف.",
                verified_identity=mapping.get("c2", {}) if verified else {},
                evidence=report.get("evidence") if verified else None,
            )
        )
    return tuple(results)


def build_prepared_workbench() -> PreparedWorkbench:
    inputs = synthetic_inputs()
    collection = prepare_batches(
        inputs,
        synthetic_fixtures_only=True,
        reference_map=fixtures.trusted_reference_map(),
        catalog=SnapshotCatalog(_asserted_catalog()),
    )
    _require(len(inputs) == len(collection.batches), "workbench: batch_count_mismatch")
    cases, overviews = [], []
    for source, entry in zip(inputs, collection.batches, strict=True):
        digest = sha256(source.raw).hexdigest()
        _require(
            entry.batch_id == source.batch_id
            and entry.input_sha256 == digest
            and entry.input_format == source.suffix,
            "workbench: batch_provenance_mismatch",
        )
        batch_cases = []
        if entry.batch is not None:
            batch = entry.batch
            _require(
                batch.report["input_sha256"] == digest
                and batch.report["input_format"] == source.suffix
                and batch.report["synthetic_only"] is True
                and batch.report["human_editing_performed"] is False,
                "workbench: batch_provenance_mismatch",
            )
            originals = load(source.raw, source.suffix)
            reports = batch.report["items"]
            _require(len(originals) == len(reports), "workbench: row_count_mismatch")
            draft_position = 0
            for ordinal, (original, report) in enumerate(zip(originals, reports, strict=True), 1):
                extras = ()
                if isinstance(original, dict) and None in original:
                    extras = tuple(original[None])
                    original = {k: v for k, v in original.items() if k is not None}
                _require(
                    report["row"] == ordinal
                    and report["original"] == original
                    and tuple(report.get("csv_extra_cells", ())) == extras,
                    "workbench: row_source_mismatch",
                )
                statuses = report["statuses"]
                rejected = "blocked-invalid" in statuses
                pending = "needs-editor-review" in statuses
                state = "rejected" if rejected else "pending" if pending else "valid"
                record = None
                question = _text_field(original, "question")
                if isinstance(original, dict) and "question" not in original:
                    question = _text_field(original, "title")
                if report["draft"] is not None:
                    _require(
                        not rejected and draft_position < len(batch.drafts),
                        "workbench: invalid_row_draft",
                    )
                    record = batch.drafts[draft_position]
                    draft_position += 1
                    _require(
                        asdict(record) == report["draft"]
                        and record.intake.external_id == _text_field(original, "external_id")
                        and record.intake.question == question
                        and record.intake.prepared_clip_url
                        == _text_field(original, "prepared_clip_url")
                        and len(record.history) == 1
                        and record.current.action == "received"
                        and record.current.title == ""
                        and record.current.answer == "",
                        "workbench: draft_source_identity_mismatch",
                    )
                reasons = tuple(_reason(f) for f in report["findings"])
                references = _references(
                    original, report["references"], report["findings"], source.suffix
                )
                review_refs = "references-unverified" in statuses
                issues = [f"{r.field}: {r.code} — {r.explanation} {r.recovery}" for r in reasons]
                if review_refs:
                    issues.append(
                        "المراجع غير متحققة أو غير مرفقة؛ لا تُنشأ إحالات بديلة، ولا تعني صلاحية الاستلام تحققها."
                    )
                batch_cases.append(
                    PreparedCase(
                        key=f"batch-{entry.batch_id}-{ordinal}",
                        external_id=_text_field(original, "external_id"),
                        question=question,
                        prepared_clip_url=_text_field(original, "prepared_clip_url"),
                        raw_source=json.dumps(original, ensure_ascii=False, sort_keys=True),
                        source_start=None,
                        source_end=None,
                        payload_sha256=digest,
                        fixture_label=f"دفعة {entry.batch_id}؛ الصف {ordinal}؛ تسلسل الحقول المحللة وليس شريحة بايتات أصلية",
                        status={"valid": "ready", "pending": "review", "rejected": "blocked"}[
                            state
                        ],
                        status_label={
                            "valid": "صالح للاستلام",
                            "pending": "معلّق للمراجعة",
                            "rejected": "مرفوض؛ لا توجد مسودة",
                        }[state],
                        issues=tuple(issues),
                        record=record,
                        references=references,
                        batch_id=entry.batch_id,
                        row_ordinal=ordinal,
                        intake_state=state,
                        original=original,
                        csv_extra_cells=extras,
                        reasons=reasons,
                        reference_review_required=review_refs,
                    )
                )
            _require(draft_position == len(batch.drafts), "workbench: extra_unassigned_draft")
        cases.extend(batch_cases)
        overviews.append(
            BatchOverview(
                entry.batch_id,
                source.suffix,
                digest,
                source.raw.decode("utf-8"),
                len(batch_cases),
                sum(c.intake_state == "valid" for c in batch_cases),
                sum(c.intake_state == "rejected" for c in batch_cases),
                sum(c.intake_state == "pending" for c in batch_cases),
                entry.error_code,
                "تعذر تحليل الدفعة. أصلح صيغة العينة المحلية ثم أعد التحضير؛ لم تُنشأ سجلات أو مسودات وهمية."
                if entry.error_code
                else "",
            )
        )
    return PreparedWorkbench(tuple(cases), tuple(overviews))
