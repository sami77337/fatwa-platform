"""Read-only preparation of a synthetic answer for its original channel."""

import re

from django.core.exceptions import SuspiciousOperation
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.delivery_planner.planner import Capabilities
from apps.delivery_planner.segmentation import SegmentationNeedsReview, parts_for_delivery
from apps.fast9_case_source_join.return_handoff import read_return_candidate
from apps.fast9_case_source_join.source_journal import JournalError

from .author_access import draft_history_required
from .reviewer_access import signed_in
from .views import _packet_exact, _source_journal_directory

TEMPLATE = "editorial_workbench/return_preparation.html"
_BLOCKERS = {
    "source_missing": "لم يُحفظ سؤال لهذه القضية في سجل التدريب.",
    "answer_missing": "لم تُحفظ مسودة جواب لهذه القضية بعد.",
    "source_deleted": "آخر حدث في المصدر حذف نص السؤال؛ يلزم فحص حالته قبل المتابعة.",
    "clarification_pending": "يوجد استيضاح ينتظر ردّ صاحب السؤال.",
    "answer_evidence_stale": "تغيّر السؤال أو ردّ الاستيضاح منذ حفظ المسودة؛ يلزم حفظ نسخة محدثة.",
    "source_reading_required": "يلزم أن يسجّل المراجع قراءة أحدث سؤال وردّ استيضاح.",
    "change_request_open": "يوجد طلب تعديل مفتوح على المسودة؛ يلزم معالجته وإغلاقه.",
    "technical_review_required": "يلزم تسليم أحدث نسخة للمراجع وإتمام فحصها الفني.",
}
_SPLIT_MESSAGES = {
    "split_requires_explicit_human_choice": "يتطلب تقسيم النص اختيارًا صريحًا قبل عرض الأجزاء.",
    "unbreakable_token_requires_human_edit": (
        "تجاوزت كلمة واحدة الحدّ؛ راجع حدّ المثال أو حرّر نسخة جديدة. لم يُختصر النص."
    ),
    "too_many_delivery_parts": (
        "يحتاج النص إلى أكثر من 16 جزءًا بهذا الحدّ؛ اختر حدًّا آخر أو راجع الصياغة."
    ),
}


def _preview_options(request):
    fields = request.GET
    value = fields.get("max_chars", "280")
    if (
        set(fields) - {"max_chars", "split"}
        or any(len(fields.getlist(key)) != 1 for key in fields)
        or not re.fullmatch(r"[1-9][0-9]{0,3}", value)
        or int(value) > 6000
        or ("split" in fields and fields["split"] != "1")
    ):
        raise ValueError("invalid_preview_options")
    return int(value), "split" in fields


@draft_history_required
@require_safe
def return_preparation(request):
    context = {
        "can_author": signed_in(request, "author"),
        "can_review": signed_in(request),
    }

    def failure(message, status):
        return render(request, TEMPLATE, {**context, "message": message}, status=status)

    try:
        max_chars, split = _preview_options(request)
    except (ValueError, SuspiciousOperation):
        return failure("استخدم خيارات المعاينة المعروضة دون معاملات إضافية أو مكررة.", 400)

    directory = _source_journal_directory()
    if directory is None:
        return failure("تعذّر فتح سجل القضية التدريبية.", 503)
    try:
        candidate = read_return_candidate(directory, synthetic_fixtures_only=True)
    except (JournalError, OSError):
        return failure("تعذّرت قراءة سجل القضية والتحقق من نسخته الحالية.", 503)

    segments = ()
    split_message = ""
    if candidate.draft is not None:
        # This profile models a training limit. It asserts no live provider
        # capability, permission, trusted approval or actual delivery intent.
        capabilities = Capabilities(
            "synthetic-origin", "preview-v1", frozenset({"text"}), max_chars, False
        )
        try:
            _, segments = parts_for_delivery(
                candidate.draft.body, capabilities, explicit_human_choice=split
            )
        except SegmentationNeedsReview as exc:
            split_message = _SPLIT_MESSAGES.get(
                str(exc), "تعذّر تجهيز أجزاء النص؛ يلزم مراجعة خيارات المعاينة."
            )

    context.update(
        candidate=candidate,
        blockers=[_BLOCKERS[code] for code in candidate.blockers],
        title=_packet_exact(candidate.draft.title) if candidate.draft else "",
        body=_packet_exact(candidate.draft.body) if candidate.draft else "",
        max_chars=max_chars,
        split=split,
        segments=segments,
        segment_rows=[
            {"ordinal": part.ordinal, "length": part.length, "text": _packet_exact(part.exact_text)}
            for part in segments
        ],
        split_message=split_message,
    )
    return render(request, TEMPLATE, context)
