"""Pure validation shared by HTML and JSON endpoints."""

import re
from dataclasses import dataclass

MAX_SOURCE_ID = 2**63 - 1
MAX_OFFSET = 20_000


class InvalidQuery(ValueError):
    pass


def bounded_int(value: str, minimum: int, maximum: int) -> int:
    if len(value) > 20 or re.fullmatch(r"[0-9]+", value) is None:
        raise InvalidQuery("Expected a bounded integer")
    result = int(value)
    if not minimum <= result <= maximum:
        raise InvalidQuery("Integer out of range")
    return result


@dataclass(frozen=True, slots=True)
class Page:
    limit: int = 30
    offset: int = 0

    def __post_init__(self) -> None:
        if (
            type(self.limit) is not int
            or type(self.offset) is not int
            or not 1 <= self.limit <= 100
            or not 0 <= self.offset <= MAX_OFFSET
        ):
            raise InvalidQuery("Invalid pagination")

    def next_offset(self, total: int) -> int | None:
        candidate = self.offset + self.limit
        return candidate if candidate < total and candidate <= MAX_OFFSET else None


def validate_search(text: str, mode: str) -> None:
    if mode not in {"exact", "literal", "normalized"}:
        raise InvalidQuery("Unknown search mode")
    if len(text) > 160 or len(text.split()) > 10:
        raise InvalidQuery("Search exceeds limits")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise InvalidQuery("Control characters are not supported")
