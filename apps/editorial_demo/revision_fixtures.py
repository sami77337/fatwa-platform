"""Two immutable, invented technical snapshots; no scholarly answer or real attribution."""

from dataclasses import replace
from hashlib import sha256

from apps.fatwa_drafts.domain import DraftRecord, Revision, State
from apps.fatwa_drafts.intake import IntakeItem, ReferenceLink


def _reference(source_id: str) -> ReferenceLink:
    # These identify invented fixture labels, not an approved archive or source book.
    return ReferenceLink(
        source_namespace="synthetic-revision-demo",
        source_book_id="SYN-BOOK",
        edition_key="SYN-EDITION",
        source_archive_sha256=sha256(b"invented-revision-demo-archive-label").hexdigest(),
        source_input_sha256=sha256(b"invented-revision-demo-input-label").hexdigest(),
        source_id=source_id,
    )


_KEEP = _reference("SYN-KEEP")
_REMOVE = _reference("SYN-REMOVE")
_ADD = _reference("SYN-ADD")

COMPARISON_RECORD = DraftRecord(
    intake=IntakeItem(
        external_id="SYN-REVISION-COMPARE-001",
        question="  سجل مصدر اصطناعي ثابت.\nلا يتضمن سؤالًا فقهيًا.  ",
        prepared_clip_url="https://example.invalid/synthetic-revision-source",
        staff_notes="علامات اختبار تقنية؛ لا بيانات شخصية أو حكم شرعي.",
        reference_links=(_KEEP, _REMOVE),
    ),
    history=(
        Revision(
            number=1,
            action="synthetic_snapshot",
            human_editor="اسم محرر اصطناعي ١",
            editorial_note="لقطة اختبار ثابتة أولى؛ ليست عملية تحرير تشغيلية.",
            state=State.PREPARATION,
            title="مثال تقني للمقارنة",
            answer="  نص اختبار تحريري فقط.\r\n\tموضع تجريبي للمراجعة.\n",
            reference_links=(_KEEP, _REMOVE),
            reviewer_notes="ملاحظة اختبار: راجع ترتيب الحقول.",
        ),
        Revision(
            number=2,
            action="synthetic_snapshot",
            human_editor="اسم محرر اصطناعي ٢",
            editorial_note="لقطة اختبار ثابتة ثانية؛ ليست اعتمادًا أو نشرًا.",
            state=State.PREPARATION,
            title="مثال تقني لمقارنة المراجعات",
            answer="  نص اختبار تحريري منقح فقط.\r\n\tموضع تجريبي للمقارنة.\n",
            reference_links=(_KEEP, _ADD),
            reviewer_notes="ملاحظة اختبار: راجع ترتيب الحقول والمراجع.",
        ),
    ),
)

# Extend the accepted two snapshots without replacing them or their source.
# Gaps deliberately ensure selectors resolve identities, never tuple positions.
_HISTORY_TEXT = replace(
    COMPARISON_RECORD.history[-1], number=4, action="synthetic_text_revision",
    human_editor="وسم محرر اصطناعي ٤", editorial_note="تغيير تقني ثابت في العنوان ونهاية النص.",
    title="مثال تقني لسجل المراجعات",
    answer=COMPARISON_RECORD.history[-1].answer + "\n",
)
_HISTORY_ORDER = replace(
    _HISTORY_TEXT, number=7, action="synthetic_reference_order",
    human_editor="وسم محرر اصطناعي ٧", editorial_note="إعادة ترتيب هويات اصطناعية للعرض فقط.",
    reference_links=(_ADD, _KEEP),
)
_HISTORY_NOTES = replace(
    _HISTORY_ORDER, number=9, action="synthetic_notes_revision",
    human_editor="وسم مراجع اصطناعي ٩", editorial_note="ملاحظة تقنية ومرجع اصطناعي مضاف.",
    reviewer_notes="ملاحظة اختبار: تثبيت ترتيب المقارنة.",
    reference_links=(_ADD, _REMOVE, _KEEP),
)
_HISTORY_LAST = replace(
    _HISTORY_NOTES, number=11, action="synthetic_snapshot",
    human_editor="وسم محرر اصطناعي ١١", editorial_note="لقطة لاحقة دون تغيير محتوى المقارنة.",
)
REVISION_HISTORY_RECORD = replace(
    COMPARISON_RECORD,
    history=(*COMPARISON_RECORD.history, _HISTORY_TEXT, _HISTORY_ORDER,
             _HISTORY_NOTES, _HISTORY_LAST),
)
