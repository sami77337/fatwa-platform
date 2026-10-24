"""Offline, synthetic reconciliation layered over the unchanged preparation contract."""

import base64
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from apps.fatwa_drafts.intake import ValidationError
from tools.content_intake.cli import MAX_REFERENCES, MAX_ROWS, parse_json
from tools.content_intake.provenance import locate_rows

from . import C1Pointer
from .batches import PreparedInput, prepare_batches

MAX_EXPORT_BYTES = 32_000_000

RECOVERY = {
    "duplicate_id": "قارن مواضع المعرّف في مجموعة التكرار وحدد السجل المقصود يدوياً في نسخة جديدة؛ لا تحذف الأصل ولا تعِد تسمية المعرّف آلياً.",
    "required": "ارجع إلى الملف الاصطناعي الأصلي لتحديد قيمة الحقل المطلوبة يدوياً، ثم قدّم نسخة جديدة مع الاحتفاظ بالأصل.",
    "media_link_missing_review_required": "أضف رابط المقطع المنجز إلى نسخة جديدة بعد مراجعته يدوياً؛ لا يجلب هذا المسار المقاطع.",
    "invalid_url": "راجع رابط المقطع يدوياً؛ يلزم HTTPS بلا بيانات دخول أو جزء تجزئة وبالمنفذ الافتراضي أو 443.",
    "invalid_http_url": "راجع بنية رابط المقطع يدوياً، ثم تحقق من توافقه مع شرط HTTPS في التحضير.",
    "needs_mapping": "اطلب مطابقة صريحة ومختبرة من المسؤول عن المصادر؛ وجود المصدر في الجرد لا يثبت المطابقة ولا يحقق الإحالة.",
    "source_pointer_missing": "راجع الإحالات في الأصل؛ لم توجد إحالة صالحة لتحديد المصدر. أضفها يدوياً إلى نسخة جديدة إن كانت متاحة.",
    "missing_source": "راجع معرّف المصدر حرفياً مقابل الجرد المقدم، ثم وفّر المصدر الاصطناعي أو صحّح الجرد يدوياً؛ لا تُستنتج مطابقة بديلة.",
    "source_inventory_not_supplied": "قدّم جرداً صريحاً لمعرّفات المصادر عبر --source-id أو أكد خلوّه عبر --empty-source-inventory؛ لم يُفترض توفر أي مصدر.",
    "csv_missing_cell": "راجع الصف وإحاطة الخلايا والفواصل في نسخة جديدة؛ الخلية المفقودة محفوظة كما وردت ولا تُملأ آلياً.",
    "csv_extra_cells": "راجع عدد الفواصل وعلامات اقتباس الخلايا في نسخة جديدة؛ الخلايا الزائدة محفوظة في التقرير.",
    "unknown_columns_or_extra_cells": "قارن أسماء الحقول بعقد الإدخال وراجع الخلايا الزائدة يدوياً؛ لا تُحذف بيانات الأصل.",
    "ambiguous_title_question": "قارن نصي العنوان والسؤال حرفياً وحدد النص المقصود يدوياً في نسخة جديدة؛ لا تُوحّد النصوص آلياً.",
    "spreadsheet_formula_text_preserved": "راجع النص يدوياً قبل فتحه في برنامج جداول؛ صُدّر كنص JSON دون تنفيذ أو تعديل محتواه.",
    "id_whitespace_not_allowed": "راجع المسافات المحيطة بالمعرّف في نسخة جديدة؛ لم يُقصّ المعرّف ولم يُطبّع.",
    "invalid_unicode_or_control": "افحص محارف التحكم والترميز في الحقل يدوياً مع الاحتفاظ بالبايتات الأصلية.",
    "MALFORMED_INPUT": "افحص ترميز UTF-8 وبنية CSV أو JSON أو JSONL وحدود الملف؛ احتفظ بالأصل وقدّم نسخة منفصلة بعد المراجعة.",
    "missing_batch": "وفّر الدفعة الاصطناعية المتوقعة بمعرّفها الصريح وأعِد التشخيص؛ لا يُنشأ محتوى بديل.",
    "record_must_be_object": "أعِد إعداد السجل يدوياً ككائن حقول مسماة وفق عقد الإدخال؛ القيمة الأصلية محفوظة للتتبع.",
    "must_be_string": "راجع نوع الحقل؛ يلزم نص حرفي بدلاً من رقم أو قائمة أو قيمة فارغة من نوع null. لا يجري تحويل تلقائي.",
    "blank_or_invalid_title": "راجع العنوان الأصلي؛ يلزم نص غير خالٍ يطابق السؤال حرفياً عند وجودهما معاً.",
    "expected_list_at_most_100": "راجع قائمة الإحالات يدوياً؛ الحد الأقصى 100 إحالة لكل صف ولا تُحذف الزيادة آلياً.",
    "expected_source_id_heading_id_string_pairs": "راجع كل إحالة؛ يلزم source_id وheading_id نصيان غير خاليين دون حقول إضافية أو مسافات محيطة أو محارف تحكم.",
    "duplicate_reference": "قارن الإحالات المتكررة في الصف وحدد المقصود يدوياً في نسخة جديدة؛ الأصل محفوظ دون حذف.",
    "duplicate_mapped_reference": "اطلب مراجعة المطابقة الصريحة؛ أكثر من مؤشر يؤول إلى الإحالة نفسها ولا تُدمج المؤشرات آلياً.",
    "invalid_pointer": "راجع معرّفي المصدر والعنوان؛ يلزم نصان غير خاليين بحد 100 محرف لكل منهما دون مسافات محيطة.",
    "invalid_text": "راجع نوع الحقل وطوله وفق عقد التحضير؛ لم يُحوّل أو يُختصر النص الأصلي.",
    "required_or_control_character": "راجع خلو الحقل ومحارف التحكم فيه يدوياً وفق عقد التحضير؛ البايتات الأصلية محفوظة.",
}


def recovery_ar(code: str, field: str = "") -> str:
    if code in RECOVERY:
        return RECOVERY[code]
    if code.startswith("too_long_max_"):
        return "راجع طول الحقل يدوياً وفق الحد المذكور في الرمز؛ لم يُختصر النص الأصلي."
    if field == "reference_links":
        return "راجع بنية الإحالة ومعرّفي المصدر والعنوان حرفياً وحدود القائمة؛ يلزم قرار بشري ولا تُستنتج مطابقة."
    return "راجع الحقل المحدد ورمز التحقق مقابل عقد الإدخال، ثم قدّم نسخة جديدة يدوياً مع إبقاء الأصل وبصمته."


def _encoded(value) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _ids(values, field):
    result = set()
    for number, value in enumerate(values, 1):
        if number > MAX_ROWS:
            raise ValidationError(f"{field}: expected_at_most_1000")
        # Use the existing exact, bounded batch identity contract for inventory IDs.
        PreparedInput(value, b"", ".json")
        if value in result:
            raise ValidationError(f"{field}: duplicate_id")
        result.add(value)
    return result


def _pointers(original):
    if not isinstance(original, dict):
        return []
    links = original.get("reference_links", [])
    if isinstance(links, str):
        try:
            links = parse_json(links) if links.strip() else []
        except (ValueError, UnicodeError):
            return []
    if not isinstance(links, list) or len(links) > MAX_REFERENCES:
        return []
    result = []
    for index, link in enumerate(links, 1):
        if not isinstance(link, dict) or set(link) != {"source_id", "heading_id"}:
            continue
        try:
            pointer = C1Pointer(**link)
        except ValidationError:
            continue
        result.append((index, pointer))
    return result


@dataclass(frozen=True, slots=True)
class DiagnosticResult:
    """Canonical immutable export; report() consumers receive detached data."""

    _json: bytes

    @property
    def report(self) -> dict:
        return json.loads(self._json)

    @property
    def has_errors(self) -> bool:
        summary = self.report["summary"]
        return bool(
            summary["error_count"]
            or summary["missing_batch_count"]
            or summary["status_counts"]["blocked-invalid"]
        )

    def json_bytes(self) -> bytes:
        return self._json

    def rows_jsonl_bytes(self) -> bytes:
        return b"".join(_encoded(row) for row in self.report["rows"])

    def preview_ar(self, *, batch_id: str | None = None, row_number: int | None = None) -> str:
        report = self.report
        summary = report["summary"]
        selected = report["rows"]
        if batch_id is not None or row_number is not None:
            if not isinstance(batch_id, str) or type(row_number) is not int or row_number < 1:
                raise ValidationError("navigation: batch_and_positive_row_required")
            selected = [
                row for row in selected if row["batch_id"] == batch_id and row["row"] == row_number
            ]
            if not selected:
                raise ValidationError("navigation: row_not_found")
        lines = [
            "تشخيص ومصالحة دفعات اصطناعية محلية — لم تُعدّل النصوص أو المصادر.",
            "وجود المصدر في الجرد لا يثبت الإحالة أو أي حكم شرعي.",
            f"الدفعات: {summary['batch_count']}؛ الصفوف: {summary['record_count']}؛ "
            f"الصفوف المحجوبة: {summary['status_counts']['blocked-invalid']}؛ "
            f"الصفوف ذات التشخيص: {summary['diagnostic_row_count']}",
        ]
        for issue in report["collection_diagnostics"]:
            lines.append(f"{issue['batch_id']}: {issue['code']} — {issue['recovery_ar']}")
        for entry in report["inputs"]:
            if entry["error_code"]:
                lines.append(f"{entry['batch_id']}: {entry['error_code']} — {entry['recovery_ar']}")
        for row in selected:
            lines.append(f"الدفعة {row['batch_id']}، الصف {row['row']}، الهوية {row['row_id']}")
            for issue in row["diagnostics"]:
                position = (
                    f"، الإحالة {issue['reference_index']}" if "reference_index" in issue else ""
                )
                lines.append(
                    f"  {issue['field']}{position}: {issue['code']} — {issue['recovery_ar']}"
                )
        selected_groups = {
            issue["group_id"]
            for row in selected
            for issue in row["diagnostics"]
            if "group_id" in issue
        }
        for group in report["duplicate_groups"]:
            if group["group_id"] in selected_groups:
                lines.append(f"مجموعة التكرار {group['group_id']}:")
                for location in group["locations"]:
                    lines.append(
                        f"  الدفعة {location['batch_id']}، الصف {location['row']} "
                        "(للعرض: --show-row BATCH ROW)"
                    )
        lines.append(
            "Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED"
        )
        return "\n".join(lines) + "\n"

    def artifacts(self) -> dict[str, bytes]:
        outputs = {
            "diagnostics.json": self.json_bytes(),
            "rows.jsonl": self.rows_jsonl_bytes(),
            "recovery.txt": self.preview_ar().encode("utf-8"),
        }
        outputs["manifest.json"] = _encoded(
            {
                "schema": "fatwa.prepared-pipeline.diagnostic-export.v1",
                "outputs": {
                    name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                    for name, raw in sorted(outputs.items())
                },
            }
        )
        if sum(map(len, outputs.values())) > MAX_EXPORT_BYTES:
            raise ValidationError("diagnostics: export_byte_limit_exceeded")
        return outputs


def diagnose_batches(
    inputs: Iterable[PreparedInput],
    *,
    synthetic_fixtures_only: bool = False,
    available_source_ids: Iterable[str] | None = None,
    expected_batch_ids: Iterable[str] = (),
) -> DiagnosticResult:
    """Reconcile explicit inventories without granting source trust or changing receipts.

    Input order is presentation order. A row_id depends only on source SHA and byte
    span; (batch_id, row_id) addresses repeated identical files. Missing inventory
    is unknown, whereas an explicit empty inventory means all pointers are missing.
    """
    # Let the existing bounded orchestrator consume and validate caller input once.
    captured = []

    def capture():
        for entry in inputs:
            captured.append(entry)
            yield entry

    collection = prepare_batches(capture(), synthetic_fixtures_only=synthetic_fixtures_only)
    expected = _ids(expected_batch_ids, "expected_batch_ids")
    inventory = None if available_source_ids is None else _ids(available_source_ids, "source_ids")
    rows, sources, groups = [], [], {}
    for source, entry in zip(captured, collection.batches, strict=True):
        sources.append(
            dict(
                batch_id=entry.batch_id,
                input_sha256=entry.input_sha256,
                input_format=entry.input_format,
                byte_length=len(source.raw),
                raw_base64=base64.b64encode(source.raw).decode("ascii"),
                error_code=entry.error_code,
                recovery_ar=recovery_ar(entry.error_code) if entry.error_code else None,
            )
        )
        if entry.batch is None:
            continue
        spans = locate_rows(source.raw, source.suffix)
        for item, span in zip(entry.batch.report["items"], spans, strict=True):
            row_id = f"{entry.input_sha256}:{span.byte_start}:{span.byte_end}"
            issues = [
                dict(
                    issue,
                    category="validation",
                    recovery_ar=recovery_ar(issue["code"], issue["field"]),
                )
                for issue in item["findings"]
            ]
            pointers = _pointers(item["original"])
            if not pointers:
                issues.append(
                    dict(
                        field="reference_links",
                        code="source_pointer_missing",
                        severity="review",
                        category="source",
                        recovery_ar=recovery_ar("source_pointer_missing"),
                    )
                )
            for index, pointer in pointers:
                code = (
                    "source_inventory_not_supplied"
                    if inventory is None
                    else "missing_source"
                    if pointer.source_id not in inventory
                    else None
                )
                if code:
                    issues.append(
                        dict(
                            field="reference_links",
                            code=code,
                            severity="review",
                            category="source",
                            reference_index=index,
                            source_id=pointer.source_id,
                            recovery_ar=recovery_ar(code),
                        )
                    )
            row = dict(
                batch_id=entry.batch_id,
                row=item["row"],
                row_id=row_id,
                provenance=dict(
                    input_sha256=entry.input_sha256,
                    byte_start=span.byte_start,
                    byte_end=span.byte_end,
                    raw_base64=base64.b64encode(span.raw).decode("ascii"),
                ),
                preparation=item,
                diagnostics=issues,
            )
            rows.append(row)
            original = item["original"]
            identity = original.get("external_id") if isinstance(original, dict) else None
            if isinstance(identity, str):
                groups.setdefault(identity, []).append(row)

    duplicates = []
    for identity, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        group_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        duplicates.append(
            dict(
                group_id=group_id,
                external_id=identity,
                cross_batch=len({row["batch_id"] for row in members}) > 1,
                locations=[
                    dict(batch_id=row["batch_id"], row=row["row"], row_id=row["row_id"])
                    for row in members
                ],
            )
        )
        for member in members:
            for issue in member["diagnostics"]:
                if issue["code"] == "duplicate_id":
                    issue["group_id"] = group_id

    missing = sorted(expected - {entry.batch_id for entry in collection.batches})
    summary = collection.workbench_summary()
    del summary["rows"]
    for status in (
        "ready-for-editor",
        "blocked-invalid",
        "needs-editor-review",
        "references-unverified",
    ):
        summary["status_counts"].setdefault(status, 0)
    summary.update(
        diagnostic_row_count=sum(bool(row["diagnostics"]) for row in rows),
        diagnostic_counts=dict(
            sorted(Counter(issue["code"] for row in rows for issue in row["diagnostics"]).items())
        ),
        duplicate_group_count=len(duplicates),
        cross_batch_duplicate_group_count=sum(group["cross_batch"] for group in duplicates),
        missing_batch_count=len(missing),
    )
    report = dict(
        schema="fatwa.prepared-pipeline.diagnostics.v1",
        synthetic_only=True,
        human_editing_performed=False,
        source_modification_performed=False,
        gates={"B": "NOT_PASSED", "C": "HOLD", "D": "HOLD", "E": "HOLD"},
        phase01="BLOCKED",
        scope="SCOPE_DEVIATION_HOLD",
        deployment="NOT_DEPLOYED",
        inventory=dict(
            available_source_ids=None if inventory is None else sorted(inventory),
            expected_batch_ids=sorted(expected),
            establishes_reference_trust=False,
        ),
        summary=summary,
        inputs=sources,
        rows=rows,
        duplicate_groups=duplicates,
        collection_diagnostics=[
            dict(
                batch_id=identity,
                code="missing_batch",
                severity="error",
                recovery_ar=recovery_ar("missing_batch"),
            )
            for identity in missing
        ],
    )
    raw = _encoded(report)
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValidationError("diagnostics: export_byte_limit_exceeded")
    return DiagnosticResult(raw)
