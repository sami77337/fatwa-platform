"""Strict staff-prepared intake; reference pointers never establish scholarly evidence."""

import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "fatwa.prepared-intake.v1"
MAX_BYTES = 1_000_000


class ValidationError(ValueError):
    """Messages contain field paths and codes, never submitted content."""


def text(value: object, path: str, *, required: bool = True, limit: int = 20000) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError(f"{path}: invalid_text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValidationError(f"{path}: invalid_utf8") from exc
    if (required and not value.strip()) or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValidationError(f"{path}: required_or_control_character")
    return value


def clip_url(value: object) -> str:
    result = text(value, "prepared_clip_url", limit=2048)
    try:
        parts = urlsplit(result)
        valid = (
            parts.scheme == "https"
            and parts.hostname
            and not parts.username
            and not parts.password
            and not parts.fragment
            and parts.port in (None, 443)
        )
    except ValueError as exc:
        raise ValidationError("prepared_clip_url: invalid_url") from exc
    if not valid or any(c.isspace() for c in result) or "\\" in result:
        raise ValidationError("prepared_clip_url: invalid_url")
    return result


@dataclass(frozen=True, slots=True)
class ReferenceLink:
    source_namespace: str
    source_book_id: str
    edition_key: str
    source_archive_sha256: str
    source_input_sha256: str
    source_id: str

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            text(value, f"reference_links.{key}", limit=100)
            if key.endswith("sha256") and (
                len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValidationError(f"reference_links.{key}: invalid_sha256")


@dataclass(frozen=True, slots=True)
class IntakeItem:
    external_id: str
    question: str
    prepared_clip_url: str
    staff_notes: str = ""
    reference_links: tuple[ReferenceLink, ...] = ()

    def __post_init__(self) -> None:
        text(self.external_id, "external_id", limit=100)
        if self.external_id != self.external_id.strip():
            raise ValidationError("external_id: surrounding_whitespace")
        text(self.question, "question")
        clip_url(self.prepared_clip_url)
        text(self.staff_notes, "staff_notes", required=False)
        if (
            not isinstance(self.reference_links, tuple)
            or any(not isinstance(ref, ReferenceLink) for ref in self.reference_links)
            or len(self.reference_links) > 100
        ):
            raise ValidationError("reference_links: invalid_links")
        if len(set(self.reference_links)) != len(self.reference_links):
            raise ValidationError("reference_links: duplicate_reference")


def _object(pairs: list[tuple[str, object]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("json: duplicate_key")
        result[key] = value
    return result


def _shape(value: object, required: set[str], optional: set[str], path: str) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - optional
    ):
        raise ValidationError(f"{path}: missing_or_unknown_fields")
    return value


def parse_intake(payload: bytes) -> tuple[IntakeItem, ...]:
    """All-or-nothing validation, bounded and strict UTF-8; no file/network access."""
    if not isinstance(payload, bytes) or len(payload) > MAX_BYTES:
        raise ValidationError("json: invalid_size_or_type")
    try:
        data = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_object)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValidationError("json: invalid_utf8_or_json") from exc
    data = _shape(data, {"schema", "items"}, set(), "envelope")
    if data["schema"] != SCHEMA:
        raise ValidationError("schema: unsupported")
    if not isinstance(data["items"], list) or not 1 <= len(data["items"]) <= 1000:
        raise ValidationError("items: expected_1_to_1000")
    result = []
    ids = set()
    for index, raw in enumerate(data["items"]):
        raw = _shape(
            raw,
            {"external_id", "question", "prepared_clip_url"},
            {"staff_notes", "reference_links"},
            f"items[{index}]",
        )
        links = raw.get("reference_links", [])
        if not isinstance(links, list) or len(links) > 100:
            raise ValidationError(f"items[{index}].reference_links: invalid_list")
        refs = tuple(
            ReferenceLink(
                **_shape(link, set(ReferenceLink.__dataclass_fields__), set(), "reference_links")
            )
            for link in links
        )
        item = IntakeItem(**{**raw, "reference_links": refs})
        if item.external_id in ids:
            raise ValidationError(f"items[{index}].external_id: duplicate_id")
        ids.add(item.external_id)
        result.append(item)
    return tuple(result)


def serialize_intake(items: tuple[IntakeItem, ...]) -> bytes:
    payload = json.dumps(
        {"schema": SCHEMA, "items": [asdict(item) for item in items]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    parse_intake(payload)
    return payload
