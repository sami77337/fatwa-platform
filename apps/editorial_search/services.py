"""Ephemeral matching copies; original strings and immutable revisions are untouched."""

import unicodedata
from collections.abc import Iterator
from dataclasses import asdict, dataclass

from apps.editorial_queue.services import QueueCatalog, QueueRow
from apps.reference.normalization import normalize_title

PAGE_SIZE = 10
MAX_RESULTS = 200
SOURCE_TYPES = (
    ("question", "السؤال الأصلي"),
    ("draft", "نص المسودة الثابتة"),
    ("reference", "معلومات الإحالة المرجعية"),
    ("record", "هوية السجل المحضّر وبياناته"),
    ("batch", "بيانات الدفعة"),
    ("status", "حالة المراجعة التقنية"),
)


@dataclass(frozen=True, slots=True)
class SearchField:
    label: str
    text: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    source: str
    case_key: str | None
    revision: int | None
    batch_id: str
    fields: tuple[SearchField, ...]
    input_sha256: str
    source_sha256: str
    fixture_label: str
    anchor: str

    @property
    def source_label(self) -> str:
        return dict(SOURCE_TYPES)[self.source]


@dataclass(frozen=True, slots=True)
class SearchPage:
    hits: tuple[SearchHit, ...]
    total: int
    page: int
    pages: int
    truncated: bool


def validate_query(q: str, source: str, batch: str, page: int) -> None:
    """Validate before loading fixtures; batch membership is checked afterwards."""
    if (
        not isinstance(q, str)
        or len(q) > 80
        or any(unicodedata.category(char) in {"Cc", "Cs"} for char in q)
        or source not in {"", *(key for key, _ in SOURCE_TYPES)}
        or len(batch) > 100
        or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in batch)
        or type(page) is not int
        or not 1 <= page <= MAX_RESULTS // PAGE_SIZE
    ):
        raise ValueError("invalid_search_query")
    q.encode("utf-8", errors="strict")


def _fields(**values: str | None) -> tuple[SearchField, ...]:
    return tuple(
        SearchField(label.replace("_", " "), text) for label, text in values.items() if text
    )


def _reference_fields(value: object, label: str) -> Iterator[SearchField]:
    """Flatten available evidence without serializing or normalizing source strings."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _reference_fields(item, f"{label}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value, 1):
            yield from _reference_fields(item, f"{label}[{index}]")
    elif isinstance(value, str) and value:
        yield SearchField(label, value)
    elif type(value) is int:
        yield SearchField(label, str(value))


def _row_documents(row: QueueRow) -> Iterator[SearchHit]:
    case = row.case

    def document(source, fields, revision=None, anchor="intake"):
        return SearchHit(
            source,
            case.key,
            revision,
            row.batch_id,
            fields,
            case.payload_sha256,
            row.source_sha256,
            case.fixture_label,
            anchor,
        )

    yield document("question", _fields(السؤال=case.question))
    yield document(
        "record",
        _fields(
            مفتاح_الحالة=case.key,
            المعرف_الخارجي=case.external_id,
            الدفعة=row.batch_id,
            المصدر=case.fixture_label,
            رابط_المقطع=case.prepared_clip_url,
            ملاحظات_الاستلام=case.record.intake.staff_notes if case.record else None,
        ),
    )
    yield document(
        "status",
        _fields(
            الحالة=case.status,
            وصف_الحالة=case.status_label,
            حالة_الاستلام=getattr(case, "intake_state", None),
            **{f"ملاحظة_{i}": issue for i, issue in enumerate(case.issues, 1)},
        ),
    )
    # Intake diagnostics have no revision identity. The existing history adapter
    # explicitly labels its diagnostics as current-snapshot references instead.
    for reference in case.references:
        current = case.record.current.number if case.key == "history" and case.record else None
        yield document(
            "reference",
            tuple(_reference_fields(reference, "الإحالة")),
            current,
            "references",
        )
    for entry in row.history:
        revision = entry.revision
        yield document(
            "draft",
            _fields(
                العنوان=revision.title,
                النص=revision.answer,
                ملاحظات_المراجع=revision.reviewer_notes,
                ملاحظة_التحرير=revision.editorial_note,
            ),
            revision.number,
            "snapshot",
        )
        yield document(
            "status",
            _fields(
                حالة_المراجعة=revision.state.value,
                العملية=revision.action,
            ),
            revision.number,
            "snapshot",
        )
        for ordinal, reference in enumerate(revision.reference_links, 1):
            yield document(
                "reference",
                tuple(_reference_fields(asdict(reference), f"مرجع_{ordinal}")),
                revision.number,
                "snapshot",
            )


def _documents(catalog: QueueCatalog, batch: str) -> Iterator[SearchHit]:
    for row in catalog.rows:
        if not batch or row.batch_id == batch:
            yield from _row_documents(row)
    for item in catalog.batches:
        if batch and item.batch_id != batch:
            continue
        source = item.source
        yield SearchHit(
            "batch",
            None,
            None,
            item.batch_id,
            _fields(
                الدفعة=item.batch_id,
                الوصف=item.label,
                الصيغة=source.input_format if source else None,
                الخطأ=source.error_code if source else None,
                الاستعادة=source.recovery if source else None,
            ),
            source.input_sha256 if source else "",
            "",
            "ملخص دفعة اصطناعية؛ ليس نص سؤال أو مسودة",
            "",
        )


def search_catalog(
    catalog: QueueCatalog,
    *,
    q: str,
    source: str = "",
    batch: str = "",
    page: int = 1,
) -> SearchPage:
    """Bounded deterministic AND matching, never a write/index persistence path."""
    validate_query(q, source, batch, page)
    if batch and batch not in {item.batch_id for item in catalog.batches}:
        raise ValueError("unknown_batch")
    terms = normalize_title(q).split()
    matches = []
    truncated = False
    if terms:
        for document in _documents(catalog, batch):
            if source and document.source != source:
                continue
            searchable = " ".join(normalize_title(field.text) for field in document.fields)
            if all(term in searchable for term in terms):
                if len(matches) == MAX_RESULTS:
                    truncated = True
                    break
                matches.append(document)
    pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        raise ValueError("page_out_of_range")
    start = (page - 1) * PAGE_SIZE
    return SearchPage(
        tuple(matches[start : start + PAGE_SIZE]), len(matches), page, pages, truncated
    )
