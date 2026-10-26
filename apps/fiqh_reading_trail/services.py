"""Pure navigation over explicit catalog topology and independently checked headings.

No Django setup, implicit catalog, I/O, edition discovery, or text matching.
The caller supplies a complete prepared catalog and a read-only evidence adapter.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from apps.editorial_workbench.services import WorkbenchCase
from apps.reference.records import (
    MAX_BIGINT,
    MAX_ROWS,
    CatalogSpec,
    HeadingRecord,
    PreparedCatalog,
    prepare_catalog,
)
from apps.reference_links.bridge import SourceIdentity
from apps.reference_links.resolution import (
    KIND,
    Heading,
    Outcome,
    ReadOnlyCatalog,
    Resolution,
    render_citation,
    resolve,
)
from apps.reference_triage.services import CaseTriage, ReferenceTriage
from apps.research_bridge.services import bridge_reference


def _positive(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_BIGINT


@dataclass(frozen=True, slots=True)
class TrailItem:
    """One exact heading, with unchanged text and explicit source topology."""

    evidence: Heading
    catalog_url: str
    citation: str
    source_id: str
    parent_source_row_id: int | None
    source_order: int
    position: int
    depth: int


@dataclass(frozen=True, slots=True)
class TrailResult:
    status: str
    reason: str
    kind: str = KIND
    current: TrailItem | None = None
    breadcrumbs: tuple[TrailItem, ...] = ()
    previous: TrailItem | None = None
    next: TrailItem | None = None
    catalog_return_url: str | None = None
    research_return_url: str | None = None


def _closed(reason: str) -> TrailResult:
    return TrailResult("unverified", reason)


def _same_heading(actual: Heading | None, expected: Heading) -> bool:
    # Dataclass equality alone regards True == 1 and 1.0 == 1. These are not
    # exact source identities or printed page assertions.
    return (
        type(actual) is Heading
        and type(actual.edition_id) is int
        and type(actual.source_row_id) is int
        and type(actual.printed_page) is int
        and actual == expected
    )


@dataclass(frozen=True, slots=True, init=False)
class ReadingTrail:
    """Immutable index for one explicit source edition (maximum 20,000 headings).

    A PreparedCatalog is a trusted input contract, not proof that an owner archive
    was inspected. Revalidation prevents malformed/altered internal snapshots;
    current catalog evidence is still required for every displayed heading.
    """

    prepared: PreparedCatalog
    edition_id: int
    identity: SourceIdentity
    _records: Mapping[int, HeadingRecord]
    _paths: Mapping[int, tuple[int, ...]]
    _headings: Mapping[int, Heading]
    _positions: Mapping[int, int]
    _ordered: tuple[int, ...]

    def __init__(self, prepared: PreparedCatalog, edition_id: int) -> None:
        if not _positive(edition_id):
            raise ValueError("An exact positive edition ID is required")
        if (
            type(prepared) is not PreparedCatalog
            or type(prepared.spec) is not CatalogSpec
            or type(prepared.records) is not tuple
            or not 1 <= len(prepared.records) <= MAX_ROWS
            or any(type(row) is not HeadingRecord for row in prepared.records)
        ):
            raise ValueError("A bounded immutable prepared catalog is required")
        try:
            checked = prepare_catalog(prepared.spec, prepared.records)
            identity = SourceIdentity(
                prepared.spec.source_namespace,
                prepared.spec.source_book_id,
                prepared.spec.edition_key,
                prepared.spec.source_archive_sha256,
                prepared.spec.source_input_sha256,
            )
        except (TypeError, AttributeError, UnicodeError) as error:
            raise ValueError("Invalid prepared catalog") from error
        if type(prepared.checksum) is not str or prepared.checksum != checked.checksum:
            raise ValueError("Prepared catalog checksum mismatch")
        records = {row.source_row_id: row for row in checked.records}
        paths: dict[int, tuple[int, ...]] = {}
        headings: dict[int, Heading] = {}
        for row in checked.records:
            reverse_path = [row.source_row_id]
            parent_id = row.parent_source_row_id
            while parent_id is not None:
                reverse_path.append(parent_id)
                parent_id = records[parent_id].parent_source_row_id
            path = tuple(reversed(reverse_path))
            paths[row.source_row_id] = path
            headings[row.source_row_id] = Heading(
                edition_id=edition_id,
                source_row_id=row.source_row_id,
                work_title=checked.spec.work_title,
                heading_title=row.title_original,
                printed_part=row.source_part,
                printed_page=row.source_page_number,
                path=tuple(records[ident].title_original for ident in path),
                source_namespace=identity.source_namespace,
                source_book_id=identity.source_book_id,
                source_input_sha256=identity.source_input_sha256,
                edition_key=identity.edition_key,
                source_archive_sha256=identity.source_archive_sha256,
            )
        ordered = tuple(row.source_row_id for row in checked.records)
        for name, value in (
            ("prepared", checked),
            ("edition_id", edition_id),
            ("identity", identity),
            ("_records", MappingProxyType(records)),
            ("_paths", MappingProxyType(paths)),
            ("_headings", MappingProxyType(headings)),
            ("_positions", MappingProxyType({ident: i for i, ident in enumerate(ordered)})),
            ("_ordered", ordered),
        ):
            object.__setattr__(self, name, value)

    def _item(self, ident: int, evidence: Heading) -> TrailItem:
        row = self._records[ident]
        return TrailItem(
            evidence=evidence,
            catalog_url=f"/fiqh/nodes/{ident}?edition={self.edition_id}",
            citation=render_citation(Resolution(Outcome.VERIFIED, (), evidence)),
            source_id=row.source_id,
            parent_source_row_id=row.parent_source_row_id,
            source_order=row.source_order,
            position=row.position,
            depth=row.depth,
        )

    def _navigate(
        self,
        source_row_id: int,
        catalog: ReadOnlyCatalog,
        origin: Heading | None = None,
    ) -> TrailResult:
        if not _positive(source_row_id):
            return _closed("exact_identity_required")
        if source_row_id not in self._records:
            return _closed("identity_not_found")
        if catalog is None or not callable(getattr(catalog, "lookup", None)):
            return _closed("catalog_required")
        position = self._positions[source_row_id]
        previous_id = self._ordered[position - 1] if position else None
        next_id = self._ordered[position + 1] if position + 1 < len(self._ordered) else None
        targets = (source_row_id, previous_id, next_id)
        evidence: dict[int, Heading] = {}
        if origin is not None:
            expected = self._headings.get(origin.source_row_id)
            if expected is None or not _same_heading(origin, expected):
                return _closed("reference_topology_mismatch")
            evidence[origin.source_row_id] = origin
            targets += (origin.source_row_id,)
        # Validate each ancestor ID as well as complete original title paths.
        # Deduplication bounds lookup to <=15 headings, or <=20 with a research
        # origin; no edition scan and no reads repeated during this invocation.
        needed = dict.fromkeys(
            ident for target in targets if target is not None for ident in self._paths[target]
        )
        for ident in needed:
            if ident in evidence:
                continue
            result = resolve({"edition_id": self.edition_id, "source_row_id": ident}, catalog)
            if result.outcome != Outcome.VERIFIED:
                return _closed(result.reasons[0])
            if not _same_heading(result.evidence, self._headings[ident]):
                return _closed("catalog_evidence_mismatch")
            evidence[ident] = result.evidence
        items = {ident: self._item(ident, heading) for ident, heading in evidence.items()}
        return TrailResult(
            status="verified",
            reason="exact_catalog_trail",
            current=items[source_row_id],
            breadcrumbs=tuple(items[ident] for ident in self._paths[source_row_id]),
            previous=items[previous_id] if previous_id is not None else None,
            next=items[next_id] if next_id is not None else None,
            catalog_return_url=f"/fiqh?edition={self.edition_id}",
        )

    def navigate(self, source_row_id: int, catalog: ReadOnlyCatalog) -> TrailResult:
        """Read exact ancestors and immediate neighbors in original source order.

        Source order is unique and authoritative, not numeric ID, alphabetical
        order, printed page, or a reconstructed depth-first traversal. Missing or
        conflicting evidence closes the whole result, never skips a neighbor.
        """
        return self._navigate(source_row_id, catalog)

    def from_reference(
        self,
        case: CaseTriage,
        reference_ordinal: int,
        catalog: ReadOnlyCatalog,
        *,
        source_row_id: int | None = None,
    ) -> TrailResult:
        """Enter or continue a trail while retaining an exact research return link.

        Recheck the original reference through the existing research bridge on
        every invocation, including when the reader has moved to another heading.
        Arbitrary return URLs and inferred case/heading associations are unsupported.
        """
        if (
            type(case) is not CaseTriage
            or type(case.case) is not WorkbenchCase
            or not isinstance(case.case.key, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", case.case.key) is None
            or type(case.references) is not tuple
            or not 1 <= len(case.references) <= 100
            or not _positive(reference_ordinal)
        ):
            return _closed("invalid_reference_occurrence")
        if any(type(ref) is not ReferenceTriage for ref in case.references):
            return _closed("invalid_reference_occurrence")
        if any(
            type(ref.ordinal) is not int or ref.ordinal != index
            for index, ref in enumerate(case.references, start=1)
        ) or reference_ordinal > len(case.references):
            return _closed("invalid_reference_occurrence")
        if catalog is None or not callable(getattr(catalog, "lookup", None)):
            return _closed("catalog_required")
        bridge = bridge_reference(case.references[reference_ordinal - 1], catalog)
        if bridge.status != "verified" or bridge.evidence is None:
            return _closed(bridge.reason)
        origin = bridge.evidence
        # The bridge compares full evidence; the topology adds exact parent IDs,
        # source order and a strict numeric check absent from dataclass equality.
        if not _positive(origin.source_row_id):
            return _closed("reference_topology_mismatch")
        target = origin.source_row_id if source_row_id is None else source_row_id
        result = self._navigate(target, catalog, origin)
        if result.status != "verified":
            return result
        return replace(
            result,
            research_return_url=(
                f"/dev/research-bridge/{case.case.key}#reference-{reference_ordinal}"
            ),
        )
