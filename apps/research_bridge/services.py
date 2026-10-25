"""Strict navigation gate over existing synthetic diagnostics and catalog reads."""

import json
from dataclasses import asdict, dataclass

from apps.reference_links.bridge import SourceIdentity
from apps.reference_links.django_adapter import DjangoCatalog
from apps.reference_links.resolution import (
    Heading,
    Outcome,
    ReadOnlyCatalog,
    SnapshotCatalog,
    resolve,
)
from apps.reference_triage.services import ReferenceTriage


@dataclass(frozen=True, slots=True)
class BridgeResult:
    status: str
    reason: str
    recovery: str
    evidence: Heading | None = None
    catalog_url: str | None = None


_RECOVERY = {
    "upstream_unverified": (
        "راجع نتيجة التحقيق والمؤشر الأصلي. يلزم ربط اصطناعي صريح ودليل تقني مكتمل؛ "
        "لا تستنتج المصدر من نص السؤال أو العنوان ولا تختَر طبعة بديلة."
    ),
    "incomplete_verified_identity": (
        "راجع هوية المصدر في العينة الثابتة: النطاق ورقم الكتاب ومفتاح الطبعة وبصمتا "
        "الأرشيف والمدخل ومعرّفا الطبعة والصف. أبقِ الربط مغلقًا حتى يتوافر دليل صريح مطابق."
    ),
    "catalog_unavailable": (
        "تعذرت قراءة الفهرس المحلي. تحقق تقنيًا من إعداد اتصال قاعدة التطوير للقراءة "
        "ثم أعد فتح الرابط. لا تستورد مصدرًا ولا تستبدل الهوية لمعالجة هذا الخطأ."
    ),
    "identity_not_found": (
        "لم توجد الطبعة أو العقدة المحددة في الفهرس المحلي. قارن معرّفي الطبعة والصف "
        "بدليل العينة الاصطناعية؛ لا تبحث عن عنوان مشابه ولا تنشئ ربطًا بديلًا."
    ),
    "catalog_evidence_mismatch": (
        "دليل الفهرس لا يطابق الهوية أو النص أو التسلسل أو الموضع المطبوع المثبت. "
        "قارن البصمات والطبعة والصف بالدليل المحلي وأحِل التعارض للفحص التقني؛ لا تعدّل المصدر."
    ),
}


def _closed(reason: str) -> BridgeResult:
    return BridgeResult(
        "unverified", reason, _RECOVERY.get(reason, _RECOVERY["catalog_evidence_mismatch"])
    )


def _expected(reference: ReferenceTriage) -> Heading:
    """Validate existing evidence only; never fill missing pins from a live catalog."""
    identity = json.loads(reference.verified_identity)
    evidence = json.loads(reference.evidence)
    if not isinstance(identity, dict) or not isinstance(evidence, dict):
        raise ValueError("Object identity and evidence required")
    pins = asdict(
        SourceIdentity(**{name: identity[name] for name in SourceIdentity.__dataclass_fields__})
    )
    if any(evidence.get(name) != value for name, value in pins.items()):
        raise ValueError("Incomplete or inconsistent source pins")
    for name in ("edition_id", "source_row_id"):
        if type(identity.get(name)) is not int or identity[name] != evidence.get(name):
            raise ValueError("Exact numeric identity required")
    if type(evidence.get("path")) is not list:
        raise ValueError("Explicit hierarchy required")
    evidence["path"] = tuple(evidence["path"])
    expected = Heading(**evidence)
    # Reuse the existing resolver's type, depth, title and printed-location rules.
    checked = resolve(
        {"edition_id": expected.edition_id, "source_row_id": expected.source_row_id},
        SnapshotCatalog((expected,)),
    )
    if checked.outcome != Outcome.VERIFIED:
        raise ValueError("Incomplete asserted evidence")
    return expected


def bridge_reference(
    reference: ReferenceTriage,
    catalog: ReadOnlyCatalog | None = None,
) -> BridgeResult:
    """Recheck one fixed synthetic occurrence against explicit live catalog IDs.

    No caller-supplied mapping, edition discovery, source import or persistence.
    Upstream synthetic verification alone never activates a catalog deep link.
    """
    if (
        reference.status != "verified"
        or reference.raw_status != "verified"
        or reference.contract_status != "VERIFIED"
        or reference.reasons
    ):
        return _closed("upstream_unverified")
    try:
        expected = _expected(reference)
    except (ValueError, TypeError, KeyError):
        return _closed("incomplete_verified_identity")
    result = resolve(
        {"edition_id": expected.edition_id, "source_row_id": expected.source_row_id},
        DjangoCatalog() if catalog is None else catalog,
    )
    if result.outcome != Outcome.VERIFIED:
        return _closed(result.reasons[0])
    # Equality checks every pin, original heading/work text, complete parent path
    # and printed location. Optional legacy pins are deliberately not accepted.
    if result.evidence != expected:
        return _closed("catalog_evidence_mismatch")
    return BridgeResult(
        "verified",
        "exact_catalog_match",
        "تطابق تقني مع الفهرس المحلي فقط؛ لا يثبت صحة علمية أو ملاءمة استشهاد أو فحص الأرشيف.",
        result.evidence,
        f"/fiqh/nodes/{expected.source_row_id}?edition={expected.edition_id}",
    )
