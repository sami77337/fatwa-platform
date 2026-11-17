"""Exact occurrence selection over the existing queue, never a title/identity join."""

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from apps.editorial_queue.services import QueueCatalog
from apps.reference_triage.services import ReferenceTriage, _reference


class ReferenceNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ReferenceCard:
    case_key: str
    ordinal: int
    revision: int | None
    origin: str
    source_text: str
    source_sha256: str
    payload_sha256: str
    fixture_label: str
    diagnostic: ReferenceTriage | None


def reference_card(
    catalog: QueueCatalog, key: str, ordinal: int, revision: int | None = None
) -> ReferenceCard:
    """Keep diagnostic and historical occurrences distinct, including duplicates."""
    if type(ordinal) is not int or not 1 <= ordinal <= 100:
        raise ReferenceNotFound
    if revision is not None and (type(revision) is not int or not 1 <= revision <= 2**31 - 1):
        raise ReferenceNotFound
    matches = [row for row in catalog.rows if row.case.key == key]
    if len(matches) != 1:
        raise ReferenceNotFound
    row = matches[0]
    diagnostic = None
    if revision is None:
        if ordinal > len(row.case.references):
            raise ReferenceNotFound
        diagnostic = _reference(row.case.references[ordinal - 1], ordinal)
        source = diagnostic.source_text
        selected_revision = (
            row.case.record.current.number if key == "history" and row.case.record else None
        )
        origin = "diagnostic"
    else:
        entries = [entry for entry in row.history if entry.revision.number == revision]
        if len(entries) != 1 or ordinal > len(entries[0].revision.reference_links):
            raise ReferenceNotFound
        source = json.dumps(
            asdict(entries[0].revision.reference_links[ordinal - 1]),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        selected_revision = revision
        origin = "revision"
    return ReferenceCard(
        key,
        ordinal,
        selected_revision,
        origin,
        source,
        sha256(source.encode("utf-8")).hexdigest(),
        row.case.payload_sha256,
        row.case.fixture_label,
        diagnostic,
    )
