"""Pure Python API. All input identities and metadata are exact, never normalized."""

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from html import escape
from typing import Mapping, Protocol, Sequence, TypeGuard

MAX_ID = 2**63 - 1
MAX_SNAPSHOT = 20_000
MAX_INPUT_BYTES = 1_000_000
KIND = "SOURCE_BOOK_TOC_NOT_FATWAS"


class Outcome(StrEnum):
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    MISMATCHED_METADATA = "mismatched_metadata"
    UNVERIFIED = "unverified"


class CatalogReadError(RuntimeError):
    """Adapter could not establish reliable read-only evidence."""


def _positive(value: object) -> TypeGuard[int]:
    return type(value) is int and 1 <= value <= MAX_ID


def _text(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


@dataclass(frozen=True, slots=True)
class Heading:
    edition_id: int
    source_row_id: int
    work_title: str
    heading_title: str
    printed_part: str | None
    printed_page: int | None
    # Complete root-to-target path, including the target, with original titles.
    path: tuple[str, ...]
    source_namespace: str
    source_book_id: str
    source_input_sha256: str
    # Older snapshots assert these via trusted caller configuration. Adapters
    # that read edition metadata supply it so the bridge can compare every pin.
    edition_key: str | None = None
    source_archive_sha256: str | None = None


class ReadOnlyCatalog(Protocol):
    def lookup(self, edition_id: int, source_row_id: int) -> Sequence[Heading]:
        """Return zero, one or at most two exact candidates; never mutate or search text."""
        ...


class SnapshotCatalog:
    """Explicit caller-supplied snapshot, at most 20,000 immutable heading records."""

    def __init__(self, rows: Sequence[Heading]) -> None:
        if len(rows) > MAX_SNAPSHOT:
            raise ValueError("Snapshot exceeds 20000 headings")
        self._rows: dict[tuple[int, int], tuple[Heading, ...]] = {}
        for row in rows:
            if not _positive(row.edition_id) or not _positive(row.source_row_id):
                raise ValueError("Invalid snapshot identity")
            key = (row.edition_id, row.source_row_id)
            self._rows[key] = (*self._rows.get(key, ()), row)[:2]

    def lookup(self, edition_id: int, source_row_id: int) -> Sequence[Heading]:
        return self._rows.get((edition_id, source_row_id), ())


@dataclass(frozen=True, slots=True)
class Resolution:
    outcome: Outcome
    reasons: tuple[str, ...]
    evidence: Heading | None = None

    def internal_payload(self) -> dict[str, object]:
        return {
            "kind": KIND,
            "outcome": self.outcome.value,
            "reasons": list(self.reasons),
            "provenance": asdict(self.evidence) if self.evidence else None,
            "toc_url": (
                f"/fiqh/nodes/{self.evidence.source_row_id}?edition={self.evidence.edition_id}"
                if self.evidence
                else None
            ),
        }


def resolve(link: Mapping[str, object], catalog: ReadOnlyCatalog) -> Resolution:
    """Optional metadata asserts exact source values. Explicit null is never omission."""
    allowed = {
        "edition_id",
        "source_row_id",
        "public_node_id",
        "work_title",
        "heading_title",
        "printed_part",
        "printed_page",
    }
    if set(link) - allowed:
        return Resolution(Outcome.UNVERIFIED, ("unknown_fields",))
    edition = link.get("edition_id")
    row = link.get("source_row_id", link.get("public_node_id"))
    if not _positive(edition) or not _positive(row):
        return Resolution(Outcome.UNVERIFIED, ("exact_identity_required",))
    if "public_node_id" in link and (
        not _positive(link["public_node_id"]) or link["public_node_id"] != row
    ):
        return Resolution(Outcome.UNVERIFIED, ("conflicting_identity",))
    for key in ("work_title", "heading_title", "printed_part", "printed_page"):
        if key in link and not (
            _positive(link[key]) if key == "printed_page" else _text(link[key])
        ):
            return Resolution(Outcome.UNVERIFIED, (f"invalid_{key}",))
    try:
        candidates = catalog.lookup(edition, row)
    except CatalogReadError:
        return Resolution(Outcome.UNVERIFIED, ("catalog_unavailable",))
    if not candidates:
        return Resolution(Outcome.NOT_FOUND, ("identity_not_found",))
    if len(candidates) != 1:
        return Resolution(Outcome.AMBIGUOUS, ("multiple_exact_candidates",))
    evidence = candidates[0]
    if type(evidence) is not Heading:
        return Resolution(Outcome.UNVERIFIED, ("incomplete_source_evidence",))
    if evidence.edition_id != edition or evidence.source_row_id != row:
        return Resolution(Outcome.UNVERIFIED, ("adapter_identity_violation",))
    if (
        not _text(evidence.work_title)
        or not _text(evidence.heading_title)
        or type(evidence.path) is not tuple
        or not 1 <= len(evidence.path) <= 5
        or not all(_text(title) for title in evidence.path)
        or evidence.path[-1] != evidence.heading_title
        or not _text(evidence.source_namespace)
        or not _text(evidence.source_book_id)
        or not _sha256(evidence.source_input_sha256)
        or (evidence.edition_key is not None and not _text(evidence.edition_key))
        or (evidence.source_archive_sha256 is not None
            and not _sha256(evidence.source_archive_sha256))
    ):
        return Resolution(Outcome.UNVERIFIED, ("incomplete_source_evidence",))
    mismatches = tuple(
        key
        for key in ("work_title", "heading_title", "printed_part", "printed_page")
        if key in link and link[key] != getattr(evidence, key)
    )
    if mismatches:
        return Resolution(Outcome.MISMATCHED_METADATA, mismatches)
    if not _text(evidence.printed_part) or not _positive(evidence.printed_page):
        return Resolution(Outcome.UNVERIFIED, ("missing_printed_location",), evidence)
    return Resolution(Outcome.VERIFIED, (), evidence)


def render_citation(result: Resolution) -> str:
    """Escaped HTML text, no safe-marking. IDs and edition remain in internal payload only."""
    if result.outcome != Outcome.VERIFIED or result.evidence is None:
        raise ValueError("Only verified evidence can be rendered")
    row = result.evidence
    return escape(
        f"إحالة إلى عنوان في فهرس {row.work_title}: {' / '.join(row.path)}"
        f"، ج {row.printed_part}، ص {row.printed_page} (عنوان فهرس، وليس نص فتوى).",
        quote=True,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def resolve_intake(raw: bytes, catalog: ReadOnlyCatalog) -> list[dict[str, object]]:
    """Validate links in prepared-intake.v1; ignore question/clip contents for association.

    Raises ValueError for malformed envelopes. No URL fetching or media operations.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Expected bounded UTF-8 JSON bytes")
    envelope = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
    if not isinstance(envelope, dict) or envelope.get("schema") != "fatwa.prepared-intake.v1":
        raise ValueError("Unsupported envelope")
    items = envelope.get("items")
    if not isinstance(items, list) or len(items) > 1000:
        raise ValueError("Expected at most 1000 items")
    results = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not _text(item.get("external_id")):
            raise ValueError("Each item requires an external_id")
        ident = item["external_id"]
        if ident in seen:
            raise ValueError("Duplicate external_id")
        seen.add(ident)
        links = item.get("reference_links", [])
        if not isinstance(links, list) or len(links) > 100:
            raise ValueError("Expected at most 100 reference links per item")
        outcomes = [
            resolve(link, catalog)
            if isinstance(link, dict)
            else Resolution(Outcome.UNVERIFIED, ("invalid_link",))
            for link in links
        ]
        results.append({"external_id": ident, "reference_links": outcomes})
    return results
