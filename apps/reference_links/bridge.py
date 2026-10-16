"""Explicit human-authored identity bridge; no I/O or implicit ID conversion."""

import json
from collections import Counter
from dataclasses import asdict, dataclass

from .resolution import (
    MAX_INPUT_BYTES, Outcome, ReadOnlyCatalog, Heading, _positive, _text, _unique_object,
    resolve, render_citation,
)


def exact_text(value: object) -> None:
    if not _text(value) or value != value.strip():
        raise ValueError("Expected exact nonblank text without surrounding whitespace")


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    source_namespace: str
    source_book_id: str
    edition_key: str
    source_archive_sha256: str
    source_input_sha256: str

    def __post_init__(self):
        for key, value in asdict(self).items():
            exact_text(value)
            if key.endswith("sha256") and (
                len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError("Invalid SHA256 pin")
        if self.source_book_id != "622":
            raise ValueError("Only the explicitly authorized book-622 TOC is supported")


@dataclass(frozen=True, slots=True)
class EditionMap:
    identity: SourceIdentity
    edition_id: int

    def __post_init__(self):
        if type(self.identity) is not SourceIdentity or not _positive(self.edition_id):
            raise ValueError("Explicit source identity and numeric edition required")


@dataclass(frozen=True, slots=True)
class HeadingMap:
    c1_source_id: str
    c1_heading_id: str
    c2_source_id: str
    source_row_id: int

    def __post_init__(self):
        for value in (self.c1_source_id, self.c1_heading_id, self.c2_source_id):
            exact_text(value)
        if not _positive(self.source_row_id):
            raise ValueError("Explicit numeric heading required")


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """One authorized source/edition per invocation. Never discover an edition."""

    edition: EditionMap
    headings: tuple[HeadingMap, ...]

    def __post_init__(self):
        if type(self.edition) is not EditionMap or type(self.headings) is not tuple:
            raise ValueError("Immutable edition and heading configuration required")
        if len(self.headings) > 20000 or any(type(h) is not HeadingMap for h in self.headings):
            raise ValueError("Invalid heading mappings")
        for keys in (
            [(h.c1_source_id, h.c1_heading_id) for h in self.headings],
            [h.c2_source_id for h in self.headings],
            [h.source_row_id for h in self.headings],
        ):
            if len(keys) != len(set(keys)):
                raise ValueError("Duplicate or colliding mapping")


@dataclass(frozen=True, slots=True)
class PointerResult:
    # Object pointers retain their original key order and JSON values. A nonobject
    # has no fields; its complete value is retained under the diagnostic sentinel
    # "$invalid_pointer" and can never be resolved.
    original_pointer: tuple[tuple[str, object], ...]
    status: Outcome
    reasons: tuple[str, ...]
    evidence: Heading | None = None
    citation: str | None = None


@dataclass(frozen=True, slots=True)
class RowResult:
    external_id: str
    reference_links: tuple[PointerResult, ...]


def resolve_prepared_pointers(
    raw: bytes, config: BridgeConfig, catalog: ReadOnlyCatalog,
) -> tuple[RowResult, ...]:
    """C1/C2 JSON envelope in; immutable per-row results out. No question matching.

    Invalid envelopes raise ValueError; invalid/unmapped pointers stay unverified.
    Original pointer fields are retained exactly, including SHA pins.
    """
    if type(config) is not BridgeConfig:
        raise ValueError("Explicit BridgeConfig required")
    if not isinstance(raw, bytes) or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Expected bounded UTF-8 JSON bytes")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if (not isinstance(data, dict) or set(data) != {"schema", "items"}
            or data["schema"] != "fatwa.prepared-intake.v1"
            or not isinstance(data["items"], list) or len(data["items"]) > 1000):
        raise ValueError("Invalid prepared envelope")
    rows, seen = [], set()
    pin = asdict(config.edition.identity)
    c1 = {(h.c1_source_id, h.c1_heading_id): h for h in config.headings}
    c2 = {h.c2_source_id: h for h in config.headings}
    for item in data["items"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid row")
        ident = item.get("external_id")
        exact_text(ident)
        if ident in seen:
            raise ValueError("Duplicate external_id")
        seen.add(ident)
        links = item.get("reference_links", [])
        if not isinstance(links, list) or len(links) > 100:
            raise ValueError("Invalid reference list")
        results = []
        # Count exact textual pointers once. Malformed JSON values are retained
        # as findings and never used as mapping keys (some are unhashable).
        originals = Counter(
            tuple(sorted(link.items())) for link in links
            if isinstance(link, dict) and all(isinstance(v, str) for v in link.values())
        )
        for link in links:
            if not isinstance(link, dict) or any(not isinstance(v, str) for v in link.values()):
                original = tuple(link.items()) if isinstance(link, dict) else (("$invalid_pointer", link),)
                results.append(PointerResult(original, Outcome.UNVERIFIED, ("invalid_pointer",)))
                continue
            original = tuple(link.items())
            canonical = tuple(sorted(original))
            duplicate = originals[canonical] > 1
            reason, mapping = "explicit_mapping_missing", None
            try:
                for value in link.values():
                    exact_text(value)
            except ValueError:
                reason = "invalid_pointer"
            else:
                if set(link) == {"source_id", "heading_id"}:
                    mapping = c1.get((link["source_id"], link["heading_id"]))
                elif set(link) == set(pin) | {"source_id"}:
                    if any(link[key] != value for key, value in pin.items()):
                        reason = "source_identity_mismatch"
                    else:
                        mapping = c2.get(link["source_id"])
                else:
                    reason = "unsupported_pointer_shape"
            if duplicate:
                mapping, reason = None, "duplicate_pointer"
            if mapping is None:
                results.append(PointerResult(original, Outcome.UNVERIFIED, (reason,)))
                continue
            resolved = resolve({"edition_id": config.edition.edition_id,
                                "source_row_id": mapping.source_row_id}, catalog)
            status, reasons = resolved.outcome, resolved.reasons
            evidence = resolved.evidence
            if status == Outcome.VERIFIED and evidence is not None:
                if type(evidence.path) is not tuple or any(getattr(evidence, key) != pin[key] for key in (
                    "source_namespace", "source_book_id", "source_input_sha256"
                )) or any(
                    getattr(evidence, key) is not None and getattr(evidence, key) != pin[key]
                    for key in ("edition_key", "source_archive_sha256")
                ):
                    status, reasons = Outcome.UNVERIFIED, ("catalog_source_pin_mismatch",)
            verified = status == Outcome.VERIFIED
            results.append(PointerResult(
                original, status, reasons, evidence if verified else None,
                render_citation(resolved) if verified else None,
            ))
        rows.append(RowResult(ident, tuple(results)))
    return tuple(rows)
