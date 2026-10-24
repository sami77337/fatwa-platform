"""Queue presentation over the published workbench's fixed synthetic read service."""

from dataclasses import dataclass
from hashlib import sha256

from apps.editorial_workbench.batches import BatchOverview, PreparedCase
from apps.editorial_workbench.services import (
    WorkbenchCase,
    WorkbenchDataError,
    build_cases,
    build_prepared_workbench,
)
from apps.revision_core.revision_history import HistoryEntry, build_history

STATUSES = (
    ("ready", "جاهز للعرض التحريري"),
    ("review", "يحتاج مراجعة"),
    ("blocked", "متعذر الاستلام"),
)
REFERENCE_FILTERS = (
    ("unresolved", "إحالات غير محسومة أو متعارضة"),
    ("missing", "دون إحالات"),
    ("verified", "كل الإحالات مطابقة اصطناعيًا"),
)
ORIGINAL_BATCH = "original"


@dataclass(frozen=True, slots=True)
class QueueRow:
    case: WorkbenchCase
    batch_id: str
    history: tuple[HistoryEntry, ...]
    verified_count: int
    unresolved_count: int
    source_sha256: str

    @property
    def reference_status(self) -> str:
        if not self.case.references:
            return "missing"
        return "unresolved" if self.unresolved_count else "verified"


@dataclass(frozen=True, slots=True)
class QueueBatch:
    batch_id: str
    label: str
    total: int
    ready: int
    review: int
    blocked: int
    source: BatchOverview | None


@dataclass(frozen=True, slots=True)
class QueueCatalog:
    rows: tuple[QueueRow, ...]
    batches: tuple[QueueBatch, ...]


@dataclass(frozen=True, slots=True)
class QueueSelection:
    rows: tuple[QueueRow, ...]
    selected: QueueRow | None
    previous: QueueRow | None
    next: QueueRow | None
    position: int | None


def build_queue() -> tuple[QueueRow, ...]:
    """Compatibility row API; details and summaries share the same catalog build."""
    return build_queue_catalog().rows


def build_queue_catalog() -> QueueCatalog:
    """Preserve both services' fixed order and exact per-row identities.

    External IDs can be missing, invalid or repeated; never join/sort by them.
    Reference diagnostics concern original intake, except the explicitly labeled
    history case, where the service reports current-snapshot identities.
    """
    original = build_cases()
    prepared = build_prepared_workbench()
    batch_ids = [ORIGINAL_BATCH, *(batch.batch_id for batch in prepared.batches)]
    if len(set(batch_ids)) != len(batch_ids):
        raise WorkbenchDataError("queue: duplicate_batch_id")
    if any(case.batch_id not in batch_ids[1:] for case in prepared.cases):
        raise WorkbenchDataError("queue: unknown_batch_id")
    cases = (*original, *prepared.cases)
    if len({case.key for case in cases}) != len(cases):
        raise WorkbenchDataError("queue: duplicate_case_key")
    rows = tuple(
        QueueRow(
            case=case,
            batch_id=case.batch_id if isinstance(case, PreparedCase) else ORIGINAL_BATCH,
            history=build_history(case.record) if case.record is not None else (),
            verified_count=sum(ref["status"] == "verified" for ref in case.references),
            unresolved_count=sum(ref["status"] != "verified" for ref in case.references),
            source_sha256=sha256(case.raw_source.encode("utf-8")).hexdigest(),
        )
        for case in cases
    )
    summaries = []
    for batch_id, source in zip(batch_ids, (None, *prepared.batches), strict=True):
        members = tuple(row for row in rows if row.batch_id == batch_id)
        summaries.append(
            QueueBatch(
                batch_id=batch_id,
                label="العينات الأصلية · المراجعات والاستلام"
                if source is None
                else f"دفعة {batch_id}",
                total=len(members),
                ready=sum(row.case.status == "ready" for row in members),
                review=sum(row.case.status == "review" for row in members),
                blocked=sum(row.case.status == "blocked" for row in members),
                source=source,
            )
        )
    return QueueCatalog(rows, tuple(summaries))


def select_queue(
    rows: tuple[QueueRow, ...],
    *,
    q: str = "",
    status: str = "",
    refs: str = "",
    batch: str = "",
    key: str | None = None,
) -> QueueSelection:
    """Filter stably and navigate immediate matching neighbors, without wrapping.

    A valid direct detail outside the filters remains inspectable, but receives
    no filtered position/neighbors. Unknown identities never select a fallback.
    """
    term = q.strip().casefold()
    matches = tuple(
        row
        for row in rows
        if (not status or row.case.status == status)
        and (not batch or row.batch_id == batch)
        and (not refs or row.reference_status == refs)
        and (
            not term
            or term
            in " ".join(
                (row.case.key, row.case.external_id or "", row.case.question or "")
            ).casefold()
        )
    )
    selected = next((row for row in rows if row.case.key == key), None)
    position = next((i for i, row in enumerate(matches) if row is selected), None)
    return QueueSelection(
        matches,
        selected,
        matches[position - 1] if position is not None and position > 0 else None,
        matches[position + 1] if position is not None and position + 1 < len(matches) else None,
        position + 1 if position is not None else None,
    )
