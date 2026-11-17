"""Bounded presentation spans projected onto untouched original source text."""

import re
import unicodedata
from dataclasses import dataclass
from heapq import merge
from itertools import islice

from apps.reference.normalization import normalize_title

from .query_terms import normalize_editorial_search, synonym_pattern

MAX_TEXT_LENGTH = 20_000
MAX_MATCHES = 100


@dataclass(frozen=True, slots=True)
class Segment:
    text: str
    matched: bool = False


@dataclass(frozen=True, slots=True)
class Highlight:
    segments: tuple[Segment, ...]
    count: int = 0
    limited: bool = False


def _normalized_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Map normalized clusters back to original code-point spans, including marks.

    NFKC can compose across clusters (e.g. Hangul Jamo). The caller verifies the
    complete normalized string before trusting any position; never guess offsets.
    """
    chars, positions = [], []
    start = 0
    while start < len(text):
        end = start + 1
        while end < len(text) and (
            unicodedata.category(text[end]).startswith("M") or text[end] == "ـ"
        ):
            end += 1
        unit = text[start:end]
        normalized = " " if unit.isspace() else normalize_title(unit)
        for char in normalized:
            if char == " " and chars and chars[-1] == " ":
                positions[-1] = (positions[-1][0], end)
            else:
                chars.append(char)
                positions.append((start, end))
        start = end
    # Match the normalizer's strip without changing original text or offsets.
    first, last = 0, len(chars)
    if chars and chars[0] == " ":
        first = 1
    if chars and chars[-1] == " ":
        last -= 1
    return "".join(chars[first:last]), positions[first:last]


def _alias_map(value: str, positions: list[tuple[int, int]]):
    chars, mapped = [], []
    end = 0
    for word in re.finditer(r"(?u)\w+", value):
        chars.append(value[end : word.start()])
        mapped.extend(positions[end : word.start()])
        normalized = normalize_editorial_search(word.group())
        chars.append(normalized)
        if normalized == word.group():
            mapped.extend(positions[word.start() : word.end()])
        else:
            # Alias lengths differ: the full original word is the evidence.
            span = (positions[word.start()][0], positions[word.end() - 1][1])
            mapped.extend([span] * len(normalized))
        end = word.end()
    chars.append(value[end:])
    mapped.extend(positions[end:])
    return "".join(chars), mapped


def highlight(text: str, query: str, match_kind: str) -> Highlight:
    """Use the matcher's literal or alias semantics; never decide result eligibility."""
    plain = (Segment(text),)
    if len(text) > MAX_TEXT_LENGTH or len(query) > 80:
        return Highlight(plain, limited=True)
    if match_kind not in {"exact", "words", "synonym"}:
        return Highlight(plain)
    value, positions = _normalized_map(text)
    if value != normalize_title(text):
        return Highlight(plain, limited=True)
    if match_kind == "synonym":
        value, positions = _alias_map(value, positions)
        if value != normalize_editorial_search(text):
            return Highlight(plain, limited=True)
        terms = tuple(dict.fromkeys(normalize_editorial_search(query).split()))
        patterns = tuple(synonym_pattern(term) for term in terms)
    else:
        terms = tuple(dict.fromkeys(normalize_title(query).split()))
        patterns = tuple(re.compile(re.escape(term)) for term in terms)
    # Merge lazy iterators in source order; cap work before materializing matches.
    streams = (
        ((match.start(), match.end()) for match in pattern.finditer(value)) for pattern in patterns
    )
    found = tuple(islice(merge(*streams), MAX_MATCHES + 1))
    spans = []
    for start, end in found[:MAX_MATCHES]:
        original = (positions[start][0], positions[end - 1][1])
        if spans and original[0] <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], original[1]))
        else:
            spans.append(original)
    segments, end = [], 0
    for start, stop in spans:
        if start > end:
            segments.append(Segment(text[end:start]))
        segments.append(Segment(text[start:stop], True))
        end = stop
    if end < len(text):
        segments.append(Segment(text[end:]))
    return Highlight(tuple(segments) or plain, len(spans), len(found) > MAX_MATCHES)
