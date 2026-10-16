"""Bounded, audited ingestion of heading metadata; Python 3.13 stdlib only.

No source retrieval, database mutations, permission grants, or publication.
A valid synthetic result is never evidence of real-source acceptance.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_RECORDS = 100_000
CONTRACT_VERSION = "fiqh-toc.v1"
REQUIRED_FIELDS = {
    "id", "parent_id", "title", "sibling_order", "part", "page", "title_origin",
}
OPTIONAL_FIELDS = {"edition", "provenance", "inference_evidence", "root_kind"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
INTEGER_PATTERN = re.compile(r"[0-9]+\Z")


class IngestError(ValueError):
    """Malformed input, manifest, unsupported format, or unsafe output path."""


class ValidationError(IngestError):
    """Strict validation failed; the report contains all discovered issues."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("validation failed; normalized export is unavailable")
        self.report = report


@dataclass(frozen=True)
class Manifest:
    dataset_id: str
    source_kind: Literal["synthetic", "owner_supplied"]
    book_id: str
    edition: str
    provenance: str
    input_sha256: str
    expected_nodes: int
    expected_roots: int
    expected_max_depth: int


@dataclass(frozen=True)
class Node:
    source_id: str
    parent_id: str | None
    title: str
    sibling_order: int
    part: int | str
    page: int
    source_part: str | int
    source_page: str | int
    title_origin: str
    inference_evidence: str | None
    root_kind: str | None
    edition: str
    provenance: str
    input_record: int
    source_metadata: dict[str, Any]


@dataclass(frozen=True)
class ImportResult:
    report: dict[str, Any]
    output_bytes: bytes | None


def canonical_json(value: Any) -> bytes:
    """UTF-8 without BOM; sorted keys and fixed separators, ending in one LF."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   allow_nan=False) + "\n"
    ).encode("utf-8")


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise IngestError(f"file exceeds the {limit}-byte limit")
    return raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise IngestError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise IngestError("non-finite JSON number")


def _json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except IngestError:
        raise
    except (ValueError, RecursionError) as exc:
        raise IngestError("malformed or excessively nested JSON") from exc


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestError(f"{label} must be a nonblank string")
    # Reject unpaired surrogates instead of failing later while writing UTF-8.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise IngestError(f"{label} must be valid Unicode") from exc
    return value


def _integer(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool):
        raise IngestError(f"{label} must be an integer >= {minimum}")
    if isinstance(value, str) and INTEGER_PATTERN.fullmatch(value):
        if len(value) > 18:
            raise IngestError(f"{label} exceeds the supported integer range")
        value = int(value)
    if not isinstance(value, int) or not minimum <= value <= 2**63 - 1:
        raise IngestError(f"{label} must be an integer >= {minimum}")
    return value


def _identifier(value: Any, label: str) -> str:
    value = _text(value, label)
    if value != value.strip() or any(unicodedata.category(c).startswith("C") for c in value):
        raise IngestError(f"{label} contains whitespace padding or control characters")
    return value


def _validate_manifest(manifest: Manifest) -> None:
    # Also protect callers that construct the public dataclass directly.
    for label in ("dataset_id", "book_id", "edition", "provenance"):
        _text(getattr(manifest, label), label)
    if manifest.book_id != "622":
        raise IngestError("this adapter supports reference book 622 only")
    if manifest.source_kind not in ("synthetic", "owner_supplied"):
        raise IngestError("source_kind must be synthetic or owner_supplied")
    if not isinstance(manifest.input_sha256, str) or not SHA256_PATTERN.fullmatch(manifest.input_sha256):
        raise IngestError("input_sha256 must be 64 lowercase hex digits")
    for label in ("expected_nodes", "expected_roots", "expected_max_depth"):
        value = getattr(manifest, label)
        if type(value) is not int:
            raise IngestError(f"{label} must be an integer")
        _integer(value, label, 1)
    if not manifest.expected_roots <= manifest.expected_nodes <= MAX_RECORDS:
        raise IngestError("invalid manifest node/root expectations")
    if manifest.expected_max_depth > manifest.expected_nodes:
        raise IngestError("invalid manifest depth expectation")


def load_manifest(path: str | Path) -> Manifest:
    """Require explicit fixture identity and completeness expectations."""
    try:
        text = _read_bounded(Path(path), MAX_MANIFEST_BYTES).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError("manifest must be UTF-8") from exc
    data = _json(text)
    fields = set(Manifest.__dataclass_fields__)
    if not isinstance(data, dict) or set(data) != fields:
        raise IngestError("manifest fields must match the documented manifest contract")
    manifest = Manifest(**data)
    _validate_manifest(manifest)
    return manifest


def _rows(raw: bytes, file_format: str, input_adapter: str) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError("input must be UTF-8") from exc
    if file_format == "json":
        rows = _json(text)
        if input_adapter == "owner-622-r1" and isinstance(rows, dict):
            from .owner_r1 import flatten_tree
            rows = flatten_tree(rows)
        if not isinstance(rows, list):
            raise IngestError("JSON input must be an array or an explicitly supported owner tree")
    elif file_format == "jsonl":
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if len(lines) > MAX_RECORDS:
            raise IngestError("too many input records")
        if any(not line.strip() for line in lines):
            raise IngestError("blank JSONL records are not allowed")
        rows = [_json(line) for line in lines]
    elif file_format == "csv":
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            headers = reader.fieldnames
            if not headers or len(headers) != len(set(headers)):
                raise IngestError("CSV requires a header without duplicate columns")
            if input_adapter == "owner-622-r1":
                from .owner_r1 import OWNER_FIELDS
                if set(headers) != OWNER_FIELDS:
                    raise IngestError("CSV columns must match the observed owner-r1 export")
            elif not REQUIRED_FIELDS <= set(headers) or set(headers) - REQUIRED_FIELDS - OPTIONAL_FIELDS:
                raise IngestError("CSV columns must match the documented heading contract")
            rows = []
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise IngestError("CSV row has a different number of fields than its header")
                # Only CSV uses empty cells for optional values and root parents.
                for key in ("parent_id", "inference_evidence", "root_kind"):
                    if row.get(key) == "":
                        row[key] = None
                for key in ("edition", "provenance"):
                    if row.get(key) == "":
                        del row[key]
                rows.append(row)
                if len(rows) > MAX_RECORDS:
                    raise IngestError("too many input records")
        except csv.Error as exc:
            raise IngestError("malformed CSV or field exceeds the CSV parser limit") from exc
    else:
        raise IngestError("format must be csv, json, or jsonl")
    if len(rows) > MAX_RECORDS:
        raise IngestError("too many input records")
    if any(not isinstance(row, dict) for row in rows):
        raise IngestError("every input record must be an object")
    return rows


def _part(value: Any) -> int | str:
    # The supplied edition has a named introductory volume, not a missing part.
    if value == "المقدمة":
        return value
    return _integer(value, "part", 1)


def _node(row: dict[str, Any], record: int, manifest: Manifest,
          source_metadata: dict[str, Any] | None = None) -> Node:
    if not REQUIRED_FIELDS <= set(row) or set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS:
        raise IngestError("heading fields must match the documented input contract")
    source_id = _identifier(row["id"], "id")
    parent_id = row["parent_id"]
    if parent_id is not None:
        parent_id = _identifier(parent_id, "parent_id")
    title = _text(row["title"], "title")
    origin = row["title_origin"]
    if origin not in ("direct", "inferred"):
        raise IngestError("title_origin must explicitly be direct or inferred")
    evidence = row.get("inference_evidence")
    if evidence is not None:
        evidence = _text(evidence, "inference_evidence")
    if origin == "inferred" and evidence is None:
        raise IngestError("inferred titles require inference_evidence")
    if origin == "direct" and evidence is not None:
        raise IngestError("direct titles must not claim inference_evidence")
    kind = row.get("root_kind")
    if kind is not None and kind not in ("introduction", "fiqh_book"):
        raise IngestError("root_kind must be introduction or fiqh_book")
    if parent_id is not None and kind is not None:
        raise IngestError("root_kind is only allowed on roots")
    return Node(
        source_id=source_id, parent_id=parent_id, title=title,
        sibling_order=_integer(row["sibling_order"], "sibling_order", 0),
        part=_part(row["part"]),
        page=_integer(row["page"], "page", 1),
        source_part=row["part"], source_page=row["page"],
        title_origin=origin, inference_evidence=evidence, root_kind=kind,
        edition=_text(row.get("edition", manifest.edition), "edition"),
        provenance=_text(row.get("provenance", manifest.provenance), "provenance"),
        input_record=record, source_metadata=source_metadata or {},
    )


def normalize_search(title: str) -> str:
    """Derived search helper only; the original title is never modified."""
    value = unicodedata.normalize("NFKC", title)
    value = "".join(c for c in value if not unicodedata.category(c).startswith("M") and c != "ـ")
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    return " ".join(value.split()).casefold()


def ingest(
    input_path: str | Path,
    manifest: Manifest,
    *,
    profile: Literal["synthetic", "real-622"],
    file_format: str | None = None,
    input_adapter: Literal["canonical", "owner-622-r1"] = "canonical",
    strict: bool = True,
) -> ImportResult:
    """Validate the full fixture, then create a canonical parent-first export.

    strict=False is diagnostic: invalid results still have no export bytes.
    A manifest identifies a trusted caller's pin; it does not authenticate a ZIP.
    """
    if profile not in ("synthetic", "real-622"):
        raise IngestError("profile must explicitly be synthetic or real-622")
    _validate_manifest(manifest)
    if input_adapter not in ("canonical", "owner-622-r1"):
        raise IngestError("unsupported input adapter")
    source = Path(input_path)
    raw = _read_bounded(source, MAX_INPUT_BYTES)
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    actual_format = file_format or source.suffix.lower().lstrip(".")
    rows = _rows(raw, actual_format, input_adapter)
    issues: list[dict[str, Any]] = []

    def issue(code: str, message: str, **location: Any) -> None:
        issues.append({"code": code, "message": message, **location})

    if actual_sha256 != manifest.input_sha256:
        issue("INPUT_SHA256_MISMATCH", "fixture bytes differ from the manifest pin")
    if profile == "synthetic" and manifest.source_kind != "synthetic":
        issue("PROFILE_SOURCE_MISMATCH", "synthetic profile requires a synthetic manifest")
    if profile == "real-622":
        if manifest.source_kind != "owner_supplied":
            issue("SOURCE_DATA_MISSING", "synthetic data cannot satisfy real-source acceptance")
        if (manifest.expected_nodes, manifest.expected_roots, manifest.expected_max_depth) != (11397, 32, 5):
            issue("REAL_SOURCE_EXPECTATIONS", "real-622 requires exactly 11397 nodes, 32 roots, depth 5")

    if input_adapter == "owner-622-r1" and profile == "real-622":
        from .owner_r1 import INPUT_PINS
        if actual_sha256 != INPUT_PINS.get(actual_format):
            issue("OWNER_R1_INPUT_PIN_MISMATCH", "input does not match a supplied owner-r1 member")

    nodes: dict[str, Node] = {}
    for record, row in enumerate(rows, 1):
        try:
            if input_adapter == "owner-622-r1":
                from .owner_r1 import adapt_row
                canonical_row, metadata = adapt_row(row, manifest)
                node = _node(canonical_row, record, manifest, metadata)
            else:
                node = _node(row, record, manifest)
        except IngestError as exc:
            issue("INVALID_RECORD", str(exc), input_record=record)
            continue
        if node.source_id in nodes:
            issue("DUPLICATE_ID", "source id appears more than once", source_id=node.source_id,
                  input_record=record)
            continue
        nodes[node.source_id] = node

    children: dict[str | None, list[Node]] = defaultdict(list)
    ordering: set[tuple[str | None, int]] = set()
    input_topological = True
    for node in nodes.values():
        key = (node.parent_id, node.sibling_order)
        if key in ordering:
            issue("DUPLICATE_SIBLING_ORDER", "siblings have ambiguous source ordering", source_id=node.source_id)
        ordering.add(key)
        children[node.parent_id].append(node)
        if node.parent_id is not None:
            if node.parent_id not in nodes:
                issue("ORPHAN_PARENT", "parent id does not exist", source_id=node.source_id)
                input_topological = False
            elif nodes[node.parent_id].input_record >= node.input_record:
                input_topological = False
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.sibling_order, node.source_id))

    # Iterative parent walks detect cycles even in disconnected components.
    done: set[str] = set()
    for start in nodes:
        trail: dict[str, int] = {}
        current: str | None = start
        while current in nodes and current not in done:
            if current in trail:
                cycle_ids = sorted(list(trail)[trail[current]:])
                issue("CYCLE", "parent edges contain a cycle", source_ids=cycle_ids)
                break
            trail[current] = len(trail)
            current = nodes[current].parent_id
        done.update(trail)

    ordered: list[tuple[Node, int]] = []
    stack = [(node, 1) for node in reversed(children[None])]
    reachable: set[str] = set()
    while stack:
        node, depth = stack.pop()
        if node.source_id in reachable:
            continue
        reachable.add(node.source_id)
        ordered.append((node, depth))
        stack.extend((child, depth + 1) for child in reversed(children[node.source_id]))
    if input_adapter == "owner-622-r1":
        from .owner_r1 import source_path_matches
        for node, depth in ordered:
            metadata = node.source_metadata
            if not source_path_matches(metadata, node.source_id, depth, nodes):
                issue("SOURCE_PATH_MISMATCH", "source path differs from parent edges or titles", source_id=node.source_id)
            if _integer(metadata["depth"], "depth", 1) != depth:
                issue("SOURCE_DEPTH_MISMATCH", "source depth differs from parent edges", source_id=node.source_id)
            if "children_count" in metadata:
                actual_children = len(children[node.source_id])
                if _integer(metadata["children_count"], "children_count", 0) != actual_children:
                    issue("SOURCE_CHILD_COUNT_MISMATCH", "source child count differs from edges", source_id=node.source_id)
                declared_leaf = metadata["is_leaf"] in (True, "True")
                if declared_leaf != (actual_children == 0):
                    issue("SOURCE_LEAF_MISMATCH", "source leaf flag differs from edges", source_id=node.source_id)
    if len(reachable) != len(nodes):
        issue("UNREACHABLE_NODES", "some nodes cannot be reached from any root",
              count=len(nodes) - len(reachable))
    root_count = len(children[None])
    max_depth = max((depth for _, depth in ordered), default=0)
    for code, actual, expected in (
        ("NODE_COUNT", len(nodes), manifest.expected_nodes),
        ("ROOT_COUNT", root_count, manifest.expected_roots),
        ("MAX_DEPTH", max_depth, manifest.expected_max_depth),
    ):
        if actual != expected:
            issue(code, "observed total differs from the completeness expectation",
                  actual=actual, expected=expected)
    if profile == "real-622":
        # Check fixed totals independently of caller-provided expectations.
        for code, actual, expected in (
            ("REAL_NODE_COUNT", len(nodes), 11397),
            ("REAL_ROOT_COUNT", root_count, 32),
            ("REAL_MAX_DEPTH", max_depth, 5),
        ):
            if actual != expected:
                issue(code, "real-source invariant failed", actual=actual, expected=expected)
        root_kinds = Counter(node.root_kind for node in children[None])
        if root_kinds != Counter({"fiqh_book": 30, "introduction": 2}):
            issue("REAL_ROOT_KINDS", "real source needs 30 fiqh_book and 2 introduction roots")

    output: bytes | None = None
    output_topological: bool | None = None
    if not issues:
        export_rows = []
        seen: set[str] = set()
        for sequence, (node, depth) in enumerate(ordered, 1):
            if node.parent_id is not None and node.parent_id not in seen:
                raise IngestError("internal error: export is not parent-first")
            seen.add(node.source_id)
            export_rows.append({
                "contract_version": CONTRACT_VERSION,
                "reference_kind": "book_heading_index",
                "book_id": manifest.book_id,
                "dataset_id": manifest.dataset_id,
                "source_kind": manifest.source_kind,
                "source_id": node.source_id,
                "parent_id": node.parent_id,
                "title": node.title,
                "search_title": normalize_search(node.title),
                "sibling_order": node.sibling_order,
                "sequence": sequence, "depth": depth,
                "part": node.part, "page": node.page,
                "source_part": node.source_part, "source_page": node.source_page,
                "edition": node.edition, "provenance": node.provenance,
                "title_origin": node.title_origin,
                "inference_evidence": node.inference_evidence,
                "root_kind": node.root_kind,
                "input_sha256": actual_sha256,
                "input_record": node.input_record,
                "source_metadata": node.source_metadata,
            })
        output = b"".join(canonical_json(row) for row in export_rows)
        output_topological = True
    origins = Counter(node.title_origin for node in nodes.values())
    report = {
        "contract_version": CONTRACT_VERSION,
        "dataset_id": manifest.dataset_id,
        "source_kind": manifest.source_kind,
        "profile": profile,
        "input_adapter": input_adapter,
        "valid": not issues,
        "source_status": "SYNTHETIC_ONLY_SOURCE_DATA_MISSING" if manifest.source_kind == "synthetic" else "OWNER_SUPPLIED_FIXTURE",
        "real_source_acceptance": (
            "STRUCTURE_VALIDATED" if profile == "real-622" and not issues else "NOT_PASSED"
        ) if profile == "real-622" else "NOT_RUN",
        "input_sha256": actual_sha256,
        "expected_input_sha256": manifest.input_sha256,
        "input_bytes": len(raw), "input_records": len(rows),
        "unique_valid_records": len(nodes),
        "roots": root_count, "max_depth": max_depth,
        "reachable_nodes": len(reachable),
        "direct_titles": origins["direct"], "inferred_titles": origins["inferred"],
        "input_topological": input_topological,
        "output_topological": output_topological,
        "output_sha256": hashlib.sha256(output).hexdigest() if output is not None else None,
        "output_bytes": len(output) if output is not None else None,
        "issues": issues,
        "deployment_status": "NOT_DEPLOYED",
        "gates": "GATES_HOLD_PHASE01_BLOCKED",
    }
    if issues and strict:
        raise ValidationError(report)
    return ImportResult(report, output)


def atomic_write(path: str | Path, raw: bytes) -> None:
    """Replace one local artifact atomically; do not create parent directories."""
    target = Path(path)
    if target.is_symlink():
        raise IngestError("refusing a symlink output target")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_export(result: ImportResult, path: str | Path) -> None:
    """Invalid and diagnostic-only results cannot be exported."""
    if result.report.get("valid") is not True or result.output_bytes is None:
        raise ValidationError(result.report)
    # Detect accidental mutation of an audit result before writing it.
    if hashlib.sha256(result.output_bytes).hexdigest() != result.report.get("output_sha256"):
        raise IngestError("output hash does not match the validated report")
    atomic_write(path, result.output_bytes)
