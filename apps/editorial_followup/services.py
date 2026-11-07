"""Fact-derived follow-up over existing fixed queue services, without new intake logic."""

from collections import defaultdict
from dataclasses import dataclass

from apps.editorial_queue.services import QueueBatch, QueueRow, build_queue_catalog
from apps.editorial_workbench.batches import PreparedCase
from apps.intake_workflow.contracts import valid_external_id
from apps.prepared_pipeline.diagnostics import recovery_ar

REASONS = (
    ("input_correction", "تصحيح أو استكمال المدخل"),
    ("missing_references", "لا توجد مؤشرات إحالة قابلة للعرض"),
    ("unresolved_references", "إحالات ملتبسة أو غير محسومة أو متعارضة"),
    ("rejected_row", "صف مرفوض"),
    ("repeated_external_id", "معرّف خارجي مشترك يحتاج مراجعة"),
    ("missing_receipt", "إيصال مسودة غير متاح في العينة"),
)
# These are existing intake display states, not editorial decisions.
STATUSES = (
    ("ready", "صالح للاستلام أو العرض المحلي"),
    ("review", "يحتاج مراجعة حسب خدمة الاستلام"),
    ("blocked", "مرفوض حسب خدمة الاستلام"),
)


@dataclass(frozen=True, slots=True)
class Reason:
    code: str
    label: str
    evidence: str
    guidance: str


@dataclass(frozen=True, slots=True)
class Preparation:
    field: str
    code: str
    severity: str
    reference_index: int | None
    explanation: str
    guidance: str


@dataclass(frozen=True, slots=True)
class FollowupRow:
    row: QueueRow
    id_group: tuple[QueueRow, ...]
    reasons: tuple[Reason, ...]
    preparation: tuple[Preparation, ...]
    references: tuple[dict, ...]


@dataclass(frozen=True, slots=True)
class FollowupCatalog:
    rows: tuple[FollowupRow, ...]
    batches: tuple[QueueBatch, ...]


@dataclass(frozen=True, slots=True)
class FollowupSelection:
    rows: tuple[FollowupRow, ...]
    selected: FollowupRow | None
    previous: FollowupRow | None
    next: FollowupRow | None
    position: int | None


def _followup(row: QueueRow, id_group: tuple[QueueRow, ...]) -> FollowupRow:
    case = row.case
    preparation = tuple(
        Preparation(
            r.field,
            r.code,
            r.severity,
            r.reference_index,
            r.explanation,
            recovery_ar(r.code, r.field),
        )
        for r in (case.reasons if isinstance(case, PreparedCase) else ())
    )
    references = tuple(ref for ref in case.references if ref["status"] != "verified")
    reasons = []

    def add(code: str, evidence: str, guidance: str) -> None:
        reasons.append(Reason(code, dict(REASONS)[code], evidence, guidance))

    # A reference mapping review alone is not evidence of invalid input.
    if (
        case.status == "blocked"
        or not case.prepared_clip_url
        or any(r.severity == "error" or r.field != "reference_links" for r in preparation)
    ):
        add(
            "input_correction",
            "رفض الاستلام أو نقص رابط المقطع أو نتائج تحقق المدخل تستدعي فحص الأصل.",
            "راجع الحقول ورموز التحقق أدناه وفي منضدة العمل. جهّز نسخة اصطناعية منفصلة للفحص خارج هذه الشاشة مع حفظ الأصل وبصمته؛ لا تُملأ القيم بالتخمين.",
        )
    if not case.references:
        add(
            "missing_references",
            "لم تُرجع الخدمة مؤشرات إحالة قابلة للعرض؛ قد تكون غير مرفقة أو ذات بنية مرفوضة.",
            "افحص حقل الإحالات في أصل السجل ونتائج تحقق بنيته. احتفظ بهوية المصدر والطبعة والموضع إن وردت؛ لا تختلق مرجعًا أو صفحة بديلة.",
        )
    if references:
        add(
            "unresolved_references",
            f"عدد المؤشرات ذات النتيجة التقنية غير المتحققة: {len(references)}.",
            "افتح رابط التحقيق لكل مؤشر أدناه وقارن هويته الأصلية ورمز السبب والدليل المتاح. اترك ما لم يُحسم كما هو؛ لا تستنتج استشهادًا أو صحة علمية.",
        )
    if case.status == "blocked":
        add(
            "rejected_row",
            case.status_label,
            "راجع أسباب رفض الصف في سياق دفعته. عند تكرار المعرّف قارن مواضعه دون دمج السجلات أو استعارة مسودة من صف آخر.",
        )
    if id_group:
        add(
            "repeated_external_id",
            f"ورد هذا المعرّف الخارجي في السجلات الموضّحة هنا. عددها {len(id_group)}.",
            "قارن الدفعة ومصدر كل سجل قبل تقرير ما إذا كانت الرسائل تخص قضية واحدة.",
        )
    if case.record is None:
        add(
            "missing_receipt",
            "لا تتوفر مسودة مرتبطة بهذا الصف في ناتج الخدمة الاصطناعية الحالي.",
            "افحص حالة الاستلام ورابط المقطع وأسباب الرفض أو التعليق قبل أي تحضير لاحق خارج الشاشة. هذا لا يثبت فقدان حدث محفوظ، ولا ينشئ إيصالًا أو مسودة.",
        )
    return FollowupRow(row, id_group, tuple(reasons), preparation, references)


def build_followup() -> FollowupCatalog:
    """Group exact identifiers for comparison; each record keeps its own stable key."""
    catalog = build_queue_catalog()
    by_id = defaultdict(list)
    for row in catalog.rows:
        external_id = valid_external_id(row.case.external_id)
        if external_id is not None:
            by_id[external_id].append(row)
    groups = {key: tuple(rows) for key, rows in by_id.items() if len(rows) > 1}
    return FollowupCatalog(
        tuple(_followup(row, groups.get(row.case.external_id, ())) for row in catalog.rows),
        catalog.batches,
    )


def select_followup(
    rows: tuple[FollowupRow, ...],
    *,
    reason: str = "",
    batch: str = "",
    status: str = "",
    key: str | None = None,
) -> FollowupSelection:
    """Stable immediate neighbors among matching follow-ups, without wrapping.

    All real identities remain directly inspectable, including rows with no
    follow-up observation; those outside the selection have no neighbors.
    """
    matches = tuple(
        item
        for item in rows
        if item.reasons
        and (not reason or any(r.code == reason for r in item.reasons))
        and (not batch or item.row.batch_id == batch)
        and (not status or item.row.case.status == status)
    )
    selected = next((item for item in rows if item.row.case.key == key), None)
    position = next((i for i, item in enumerate(matches) if item is selected), None)
    return FollowupSelection(
        matches,
        selected,
        matches[position - 1] if position is not None and position > 0 else None,
        matches[position + 1] if position is not None and position + 1 < len(matches) else None,
        position + 1 if position is not None else None,
    )
