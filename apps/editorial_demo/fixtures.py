"""Explicit synthetic display fixtures; no intake adapter or mutable stage."""

from dataclasses import dataclass

SCHEMA = "fatwa.prepared-intake.v1"
STATUSES = {
    "received": "استلام اصطناعي",
    "draft_preparation": "تحضير مسودة",
    "needs_revision": "تحتاج مراجعة",
}


@dataclass(frozen=True)
class PreviewRow:
    external_id: str
    title: str
    question: str
    status: str
    prepared_clip_url: str = "https://example.invalid/finished-clip-placeholder"
    reference_links: tuple = ()

    @property
    def status_label(self) -> str:
        return STATUSES[self.status]


ROWS = (
    PreviewRow("SYN-001", "مثال الطهارة", "سؤال اصطناعي: كيف يراجع سؤال الطهارة؟", "received"),
    PreviewRow(
        "SYN-002", "مثال الصلاة", "سؤال اصطناعي: كيف تراجع إحالة الصلاة؟", "draft_preparation"
    ),
    PreviewRow(
        "SYN-003", "مثال الصيام", "سؤال اصطناعي: كيف يحفظ أصل سؤال الصيام؟", "needs_revision"
    ),
    PreviewRow(
        "SYN-004", "مثال الزكاة", "سؤال اصطناعي: كيف تعرض إحالة الزكاة؟", "draft_preparation"
    ),
)
