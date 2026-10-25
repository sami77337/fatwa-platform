"""Presentation over Wave3 diagnostics and FAST2 resolution via the workbench.

No new resolver, catalogue lookup, source discovery, persistence or citation.
Every occurrence keeps its case key and ordinal, including duplicate identities.
"""

import json
from dataclasses import dataclass
from hashlib import sha256

from apps.editorial_workbench.services import (
    WorkbenchCase,
    WorkbenchDataError,
    build_cases,
    build_prepared_workbench,
)

STATUSES = (
    ("verified", "مطابق تقنيًا"),
    ("unresolved", "غير محسوم"),
    ("mismatched", "متعارض تقنيًا"),
    ("missing", "بلا مؤشرات قابلة للعرض"),
)
_GROUPS = {
    "verified": "verified",
    "unresolved": "unresolved",
    "unverified": "unresolved",
    "not_found": "unresolved",
    "ambiguous": "unresolved",
    "mismatched": "mismatched",
    "mismatched_metadata": "mismatched",
}
_RECOVERY = {
    "verified": "احتفظ بهوية المصدر ودليل المطابقة كما وردا. المطابقة التقنية لا تكفي لاختيار استشهاد أو تقرير صحة علمية.",
    "unresolved": "راجع رمز السبب والمؤشر الأصلي والربط الاصطناعي الصريح في المصدر المحلي. عند نقص الدليل اترك الإحالة غير محسومة؛ لا تخمّن عنوانًا أو صفحة أو إحالة بديلة.",
    "mismatched": "قارن هوية المصدر والطبعة والصف والبيانات المثبتة بالدليل المتاح. أحِل التعارض للفحص البشري خارج هذه الشاشة؛ لا تستبدل الهوية أو تعدّل الفهرس المحمي.",
}


@dataclass(frozen=True, slots=True)
class Summary:
    records: int
    references: int
    verified: int
    unresolved: int
    mismatched: int
    missing: int


@dataclass(frozen=True, slots=True)
class ReferenceTriage:
    ordinal: int
    status: str
    label: str
    raw_status: str
    contract_status: str
    explanation: str
    reason_explanations: tuple[str, ...]
    reasons: tuple[str, ...]
    recovery: str
    original_identity: str
    verified_identity: str
    evidence: str
    source_text: str
    source_start: int | None
    source_end: int | None
    source_sha256: str


@dataclass(frozen=True, slots=True)
class CaseTriage:
    case: WorkbenchCase
    batch_id: str
    references: tuple[ReferenceTriage, ...]
    summary: Summary
    source_sha256: str


@dataclass(frozen=True, slots=True)
class BatchTriage:
    batch_id: str
    label: str
    input_sha256: str
    summary: Summary
    error_code: str | None = None
    recovery: str = ""


@dataclass(frozen=True, slots=True)
class Investigation:
    cases: tuple[CaseTriage, ...]
    batches: tuple[BatchTriage, ...]
    summary: Summary


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _reference(raw: dict, ordinal: int) -> ReferenceTriage:
    status = _GROUPS.get(raw["status"])
    if status is None or raw["reference_ordinal"] != ordinal:
        raise WorkbenchDataError("triage: invalid_reference_decision")
    source = raw["source"]
    return ReferenceTriage(
        ordinal,
        status,
        dict(STATUSES)[status],
        raw["status"],
        raw["contract_status"],
        raw["explanation_ar"],
        tuple(raw["reason_explanations_ar"]),
        tuple(raw["reasons"]),
        _RECOVERY[status],
        _json(raw.get("original_identity", {})),
        _json(raw["verified_identity"]),
        _json(raw["evidence"]),
        source["text"],
        source["start"],
        source["end"],
        sha256(source["text"].encode("utf-8")).hexdigest(),
    )


def summarize(rows: tuple[CaseTriage, ...]) -> Summary:
    """Count references once; missing is a separate count of records, not links."""
    refs = tuple(ref for row in rows for ref in row.references)
    return Summary(
        len(rows),
        len(refs),
        sum(ref.status == "verified" for ref in refs),
        sum(ref.status == "unresolved" for ref in refs),
        sum(ref.status == "mismatched" for ref in refs),
        sum(not row.references for row in rows),
    )


def build_investigation() -> Investigation:
    """Only built-in fixtures; upstream services own all technical decisions."""
    base = build_cases()
    prepared = build_prepared_workbench()
    rows = []
    for case in (*base, *prepared.cases):
        refs = tuple(_reference(raw, i) for i, raw in enumerate(case.references, 1))
        batch_id = getattr(
            case, "batch_id", "revision-history" if case.key == "history" else "wave7"
        )
        summary = Summary(
            1,
            len(refs),
            sum(ref.status == "verified" for ref in refs),
            sum(ref.status == "unresolved" for ref in refs),
            sum(ref.status == "mismatched" for ref in refs),
            int(not refs),
        )
        rows.append(
            CaseTriage(
                case, batch_id, refs, summary, sha256(case.raw_source.encode("utf-8")).hexdigest()
            )
        )
    cases = tuple(rows)
    batches = []
    for batch_id, label in (
        ("revision-history", "سجل المراجعات الثابت"),
        ("wave7", "دفعة Wave7 الاصطناعية"),
    ):
        members = tuple(row for row in cases if row.batch_id == batch_id)
        batches.append(
            BatchTriage(
                batch_id,
                label,
                members[0].case.payload_sha256 if members else "",
                summarize(members),
            )
        )
    for batch in prepared.batches:
        members = tuple(row for row in cases if row.batch_id == batch.batch_id)
        batches.append(
            BatchTriage(
                batch.batch_id,
                f"دفعة {batch.batch_id} ({batch.input_format})",
                batch.input_sha256,
                summarize(members),
                batch.error_code,
                batch.recovery,
            )
        )
    return Investigation(cases, tuple(batches), summarize(cases))
