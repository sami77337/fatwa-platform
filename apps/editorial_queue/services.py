"""Queue presentation over the published workbench's fixed synthetic read service."""

from dataclasses import dataclass
from hashlib import sha256

from apps.editorial_workbench.services import WorkbenchCase, WorkbenchDataError, build_cases
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


@dataclass(frozen=True, slots=True)
class QueueRow:
    case: WorkbenchCase
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
class QueueSelection:
    rows: tuple[QueueRow, ...]
    selected: QueueRow | None
    previous: QueueRow | None
    next: QueueRow | None
    position: int | None


def build_queue() -> tuple[QueueRow, ...]:
    """Preserve the service's fixed manifest order and exact per-row identities.

    External IDs can be missing, invalid or repeated; never join/sort by them.
    Reference diagnostics concern original intake, except the explicitly labeled
    history case, where the service reports current-snapshot identities.
    """
    cases = build_cases()
    if len({case.key for case in cases}) != len(cases):
        raise WorkbenchDataError("queue: duplicate_case_key")
    return tuple(
        QueueRow(
            case=case,
            history=build_history(case.record) if case.record is not None else (),
            verified_count=sum(ref["status"] == "verified" for ref in case.references),
            unresolved_count=sum(ref["status"] != "verified" for ref in case.references),
            source_sha256=sha256(case.raw_source.encode("utf-8")).hexdigest(),
        )
        for case in cases
    )


def select_queue(
    rows: tuple[QueueRow, ...],
    *,
    q: str = "",
    status: str = "",
    refs: str = "",
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
