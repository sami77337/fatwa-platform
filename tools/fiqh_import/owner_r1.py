"""Explicit adapter for the supplied, audited 2026-10-11 heading export.

Only heading fields are accepted. No archive scripts or instructions are executed.
"""
from __future__ import annotations

from typing import Any

from .ingest import IngestError, Manifest, _integer, _text

OWNER_FIELDS = {
    "id", "parent_id", "title", "depth", "position_among_siblings",
    "children_count", "is_leaf", "source_page_id", "source_part",
    "source_page_number", "source_entry_number", "path_ids", "path_titles",
    "lucene_title_key",
}
NESTED_FIELDS = {
    "id", "parent_id", "title", "depth", "order", "source_page_id",
    "source_part", "source_page_number",
}
INPUT_PINS = {
    "csv": "8e988dba18bff6c3b8052174f5c00e2b19b790f47ba73cc6aa6936cda77fa441",
    "jsonl": "37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14",
    "json": "05f76f0230ec5cff7b6955a9c9d7e6c2c0190bdcc2e9fbae36945cde970bd80f",
}
INTRODUCTION_IDS = frozenset({"1", "23"})
FIQH_BOOK_IDS = frozenset({
    "25", "69", "1321", "1752", "2214", "2618", "3452", "3956",
    "5568", "6833", "7194", "7464", "7877", "8053", "8550", "8898",
    "9241", "9306", "9370", "9474", "9532", "9693", "9873", "10131",
    "10510", "10593", "10649", "10818", "11142", "11289",
})


def flatten_tree(value: Any) -> list[dict[str, Any]]:
    """Flatten the supplied nested JSON without copying nested children."""
    fields = {"source", "scope", "total_nodes", "root_count", "roots"}
    if not isinstance(value, dict) or set(value) != fields or not isinstance(value["roots"], list):
        raise IngestError("owner-r1 JSON must have the documented tree envelope")
    if value["scope"] != "CONTENTS_TREE_ONLY_NOT_FULL_TEXT":
        raise IngestError("unsupported owner tree scope")
    if not isinstance(value["source"], dict) or value["source"].get("work_id") != 622:
        raise IngestError("owner tree source must identify book 622")
    rows: list[dict[str, Any]] = []
    stack = [(node, None) for node in reversed(value["roots"])]
    while stack:
        node, expected_parent = stack.pop()
        if not isinstance(node, dict) or set(node) != NESTED_FIELDS | {"children"}:
            raise IngestError("owner tree node fields differ from the pinned source format")
        if node["parent_id"] != expected_parent:
            raise IngestError("nested children disagree with explicit parent_id")
        if not isinstance(node["children"], list):
            raise IngestError("owner tree children must be an array")
        rows.append({key: item for key, item in node.items() if key != "children"})
        if len(rows) > 100_000:
            raise IngestError("too many owner tree nodes")
        stack.extend((child, node["id"]) for child in reversed(node["children"]))
    if _integer(value["total_nodes"], "total_nodes", 1) != len(rows):
        raise IngestError("owner JSON total_nodes does not match its full tree")
    if _integer(value["root_count"], "root_count", 1) != len(value["roots"]):
        raise IngestError("owner JSON root_count does not match its roots")
    return rows


def _source_id(value: Any, label: str) -> str:
    _integer(value, label, 1)
    # Numeric JSON IDs have no lexical padding; CSV IDs retain their exact string.
    return str(value)


def adapt_row(row: dict[str, Any], manifest: Manifest) -> tuple[dict[str, Any], dict[str, Any]]:
    nested = set(row) == NESTED_FIELDS
    if not nested and set(row) != OWNER_FIELDS:
        raise IngestError("owner-r1 row fields differ from the observed heading export")
    source_id = _source_id(row["id"], "id")
    parent = row["parent_id"]
    parent_id = None if parent is None else _source_id(parent, "parent_id")
    _integer(row["source_page_id"], "source_page_id", 1)
    _integer(row["depth"], "depth", 1)
    if not nested:
        if row["lucene_title_key"] != "622-" + source_id:
            raise IngestError("owner title key does not identify this book and heading")
        _integer(row["children_count"], "children_count", 0)
        if type(row["is_leaf"]) is not bool and row["is_leaf"] not in ("True", "False"):
            raise IngestError("invalid owner is_leaf flag")
        entry = row["source_entry_number"]
        if entry not in (None, ""):
            _integer(entry, "source_entry_number", 1)
        for label in ("path_ids", "path_titles"):
            if not isinstance(row[label], (str, list)) or not row[label]:
                raise IngestError(f"owner {label} must preserve nonempty source path metadata")
            if isinstance(row[label], str):
                _text(row[label], label)
            elif label == "path_ids":
                for item in row[label]:
                    _integer(item, label, 1)
            else:
                for item in row[label]:
                    _text(item, label)
    root_kind = None
    if parent_id is None:
        if source_id in INTRODUCTION_IDS:
            root_kind = "introduction"
        elif source_id in FIQH_BOOK_IDS:
            root_kind = "fiqh_book"
        else:
            raise IngestError("unrecognized root identity for the pinned owner-r1 edition")
    canonical = {
        "id": source_id, "parent_id": parent_id, "title": _text(row["title"], "title"),
        "sibling_order": row["order" if nested else "position_among_siblings"],
        "part": row["source_part"], "page": row["source_page_number"],
        "title_origin": "direct", "root_kind": root_kind,
        "edition": manifest.edition, "provenance": manifest.provenance,
    }
    # Keep the original typed ID, source page ID, title key and path metadata.
    metadata = {key: item for key, item in row.items() if key != "title"}
    return canonical, metadata


def source_path_matches(metadata: dict[str, Any], source_id: str, depth: int,
                        nodes: dict[str, Any]) -> bool:
    """Validate supplied path claims without replacing their original text."""
    if "path_ids" not in metadata:
        return True  # Nested JSON has no declared path fields.
    ids = metadata["path_ids"]
    titles = metadata["path_titles"]
    if isinstance(ids, str):
        ids = ids.split(" > ")
    if isinstance(titles, str):
        titles = titles.split(" ← ")
    ids = [str(value) for value in ids]
    if len(ids) != depth or len(titles) != depth or ids[-1] != source_id:
        return False
    for index, ancestor_id in enumerate(ids):
        ancestor = nodes.get(ancestor_id)
        expected_parent = ids[index - 1] if index else None
        if ancestor is None or ancestor.parent_id != expected_parent or ancestor.title != titles[index]:
            return False
    return True
