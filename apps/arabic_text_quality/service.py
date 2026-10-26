"""Pure diagnostics: no normalization, persistence, permissions or source writes."""

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Literal

from apps.fatwa_drafts.domain import Revision, State
from apps.revision_core import revision_comparison

MAX_TEXT_LENGTH = revision_comparison.MAX_TEXT_LENGTH
Severity = Literal["info", "warning", "error"]
_FORMS: tuple[Literal["NFC", "NFKC"], ...] = ("NFC", "NFKC")
_ENDINGS = re.compile(r"\r\n|[\r\n\x85\u2028\u2029]")
_HORIZONTAL = re.compile(r"[^\S\r\n\x85\u2028\u2029]+")
_OPEN_EMBED = {"\u202a", "\u202b", "\u202d", "\u202e"}
_OPEN_ISOLATE = {"\u2066", "\u2067", "\u2068"}
_BIDI = _OPEN_EMBED | _OPEN_ISOLATE | {"\u202c", "\u2069", "\u200e", "\u200f", "\u061c"}


@dataclass(frozen=True, slots=True)
class Location:
    side: str
    start: int
    end: int
    line: int
    column: int
    end_line: int
    end_column: int
    original: str
    codepoints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    location: Location
    related_location: Location | None = None


@dataclass(frozen=True, slots=True)
class SourceText:
    side: str
    text: str
    sha256: str
    codepoint_length: int


@dataclass(frozen=True, slots=True)
class QualityReport:
    kind: str
    mode: str
    sources: tuple[SourceText, ...]
    diagnostics: tuple[Diagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        diagnostics = [asdict(item) for item in self.diagnostics]
        for item in diagnostics:
            item["location"]["codepoints"] = list(item["location"]["codepoints"])
            if item["related_location"] is not None:
                item["related_location"]["codepoints"] = list(
                    item["related_location"]["codepoints"]
                )
        return {
            "schema_version": 1,
            "unicode_version": unicodedata.unidata_version,
            "kind": self.kind,
            "mode": self.mode,
            "synthetic_only": True,
            "source_preserved": True,
            "gates": "NOT_DEPLOYED / GATES_HOLD",
            "sources": [asdict(source) for source in self.sources],
            "diagnostics": diagnostics,
        }

    def to_json(self) -> str:
        """ASCII escaping prevents embedded terminal controls/bidi in emitted reports."""
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _guard(synthetic_only: bool, kind: str) -> None:
    if synthetic_only is not True:
        raise ValueError("synthetic_only_required")
    if kind not in ("question", "revision"):
        raise ValueError("invalid_text_kind")


def _validate(text: str) -> None:
    if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
        raise ValueError("text_invalid_or_too_long")
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("text_invalid_unicode") from exc


class _Source:
    """Precomputed code-point coordinates, independent of rendered bidi ordering."""

    def __init__(self, text: str, side: str) -> None:
        self.text = text
        self.side = side
        self.positions: list[tuple[int, int]] = []
        line, column = 1, 1
        for index, char in enumerate(text):
            self.positions.append((line, column))
            if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                column += 1
            elif char in "\r\n\x85\u2028\u2029":
                line, column = line + 1, 1
            else:
                column += 1
        self.positions.append((line, column))

    def location(self, start: int, end: int) -> Location:
        line, column = self.positions[start]
        end_line, end_column = self.positions[end]
        original = self.text[start:end]
        return Location(
            self.side,
            start,
            end,
            line,
            column,
            end_line,
            end_column,
            original,
            tuple(f"U+{ord(char):04X}" for char in original),
        )

    def record(self) -> SourceText:
        return SourceText(
            self.side,
            self.text,
            hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
            len(self.text),
        )


def _envelope(before: str, after: str) -> tuple[int, int, int, int]:
    """Smallest contiguous differing enclosure; no approximate grapheme offsets."""
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    old_end, new_end = len(before), len(after)
    while old_end > start and new_end > start and before[old_end - 1] == after[new_end - 1]:
        old_end -= 1
        new_end -= 1
    return start, old_end, start, new_end


def _inspect(source: _Source) -> list[Diagnostic]:
    text = source.text
    found: list[Diagnostic] = []

    def add(code: str, severity: Severity, message: str, start: int, end: int) -> None:
        found.append(Diagnostic(code, severity, message, source.location(start, end)))

    stack: list[tuple[str, int]] = []
    isolate_indexes: list[int] = []

    def close_paragraph() -> None:
        for _, position in stack:
            add(
                "bidi_unclosed_scope",
                "error",
                "Bidi scope ends without its closer.",
                position,
                position + 1,
            )
        stack.clear()
        isolate_indexes.clear()

    for index, char in enumerate(text):
        category = unicodedata.category(char)
        if unicodedata.bidirectional(char) == "B":
            close_paragraph()
        if char in _BIDI:
            add(
                "bidi_control",
                "info",
                "Explicit bidi formatting needs human review.",
                index,
                index + 1,
            )
            if char in {"\u202d", "\u202e"}:
                add(
                    "bidi_override",
                    "warning",
                    "Directional override can obscure logical order.",
                    index,
                    index + 1,
                )
            if char in _OPEN_EMBED:
                stack.append(("embedding", index))
            elif char in _OPEN_ISOLATE:
                isolate_indexes.append(len(stack))
                stack.append(("isolate", index))
            elif char == "\u202c":
                if stack and stack[-1][0] == "embedding":
                    stack.pop()
                else:
                    add(
                        "bidi_unmatched_closer",
                        "error",
                        "PDF has no matching embedding here.",
                        index,
                        index + 1,
                    )
            elif char == "\u2069":
                if not isolate_indexes:
                    add(
                        "bidi_unmatched_closer",
                        "error",
                        "PDI has no matching isolate here.",
                        index,
                        index + 1,
                    )
                else:
                    # UAX #9: PDI also terminates embeddings nested inside its isolate.
                    del stack[isolate_indexes.pop() :]
        elif char in {"\u200c", "\u200d"}:
            add(
                "join_control",
                "info",
                "Join control may be intentional Arabic shaping.",
                index,
                index + 1,
            )
        elif category == "Cc" and char not in "\t\r\n\x85":
            add(
                "control_character",
                "warning",
                "Potentially problematic control character.",
                index,
                index + 1,
            )
        elif category == "Cf":
            add(
                "format_character",
                "warning",
                "Invisible format character needs review.",
                index,
                index + 1,
            )
        if char.isspace() and char not in " \r\n\x85\u2028\u2029":
            add(
                "unusual_whitespace",
                "info" if char == "\t" else "warning",
                "Whitespace character may affect layout or exact matching.",
                index,
                index + 1,
            )
    close_paragraph()

    endings = list(_ENDINGS.finditer(text))
    mixed = len({match.group() for match in endings}) > 1
    for match in endings:
        if mixed:
            add(
                "mixed_line_endings",
                "warning",
                "Source contains multiple line-ending styles.",
                match.start(),
                match.end(),
            )
        if match.group() not in {"\n", "\r\n"}:
            add(
                "unusual_line_ending",
                "warning",
                "Non-LF/CRLF line ending needs review.",
                match.start(),
                match.end(),
            )
    for match in _HORIZONTAL.finditer(text):
        start, end = match.span()
        if start == 0 or text[start - 1] in "\r\n\x85\u2028\u2029":
            add(
                "leading_whitespace",
                "info",
                "Leading whitespace may be intentional indentation.",
                start,
                end,
            )
        if end == len(text) or text[end] in "\r\n\x85\u2028\u2029":
            add("trailing_whitespace", "warning", "Trailing whitespace needs review.", start, end)
        if end - start > 1:
            add(
                "repeated_whitespace",
                "info",
                "Repeated whitespace may be intentional layout.",
                start,
                end,
            )
    for form in _FORMS:
        normalized = unicodedata.normalize(form, text)
        if normalized != text:
            start, end, _, _ = _envelope(text, normalized)
            add(
                "normalization_" + form.lower(),
                "info",
                f"{form} would change this enclosing source span; source remains unchanged.",
                start,
                end,
            )
    return found


def _report(
    kind: str, mode: str, sources: tuple[_Source, ...], diagnostics: list[Diagnostic]
) -> QualityReport:
    sides = {source.side: index for index, source in enumerate(sources)}
    ordered = sorted(
        diagnostics,
        key=lambda item: (
            sides[item.location.side],
            item.location.start,
            item.location.end,
            item.code,
            item.related_location.start if item.related_location else -1,
        ),
    )
    return QualityReport(kind, mode, tuple(source.record() for source in sources), tuple(ordered))


def inspect_text(
    text: str, *, synthetic_only: bool = False, kind: str = "question"
) -> QualityReport:
    """Inspect fabricated text without changing even one original code point."""
    _guard(synthetic_only, kind)
    _validate(text)
    source = _Source(text, "source")
    return _report(kind, "inspection", (source,), _inspect(source))


def _snapshot(text: str) -> Revision:
    return Revision(
        1, "synthetic_quality", "synthetic", "synthetic", State.RECEIVED, text, "", (), ""
    )


def _changes(field: revision_comparison.TextComparison) -> Iterator[tuple[int, int, int, int]]:
    """Recover paired edit ranges from the authoritative lossless comparison parts."""
    old_index = new_index = old_offset = new_offset = 0
    while old_index < len(field.before) or new_index < len(field.after):
        old_start, new_start = old_offset, new_offset
        while old_index < len(field.before) and field.before[old_index].kind == "removed":
            old_offset += len(field.before[old_index].text)
            old_index += 1
        while new_index < len(field.after) and field.after[new_index].kind == "added":
            new_offset += len(field.after[new_index].text)
            new_index += 1
        if (old_start, new_start) != (old_offset, new_offset):
            yield old_start, old_offset, new_start, new_offset
        if old_index < len(field.before):
            old_offset += len(field.before[old_index].text)
            old_index += 1
        if new_index < len(field.after):
            new_offset += len(field.after[new_index].text)
            new_index += 1


def _compare(
    old: _Source, new: _Source, field: revision_comparison.TextComparison
) -> list[Diagnostic]:
    found = _inspect(old) + _inspect(new)
    for i, j, k, end in _changes(field):
        left, right = old.text[i:j], new.text[k:end]
        location, related = old.location(i, j), new.location(k, end)
        if any(char.isspace() for char in left + right):
            found.append(
                Diagnostic(
                    "whitespace_change",
                    "warning",
                    "Edit contains changed whitespace; human review determines intent.",
                    location,
                    related,
                )
            )
        if _ENDINGS.findall(left) != _ENDINGS.findall(right):
            found.append(
                Diagnostic(
                    "line_ending_change",
                    "warning",
                    "Edit changes a line ending or line boundary.",
                    location,
                    related,
                )
            )
    if old.text != new.text:
        forms = [
            form
            for form in _FORMS
            if unicodedata.normalize(form, old.text) == unicodedata.normalize(form, new.text)
        ]
        if forms:
            i, j, k, end = _envelope(old.text, new.text)
            found.append(
                Diagnostic(
                    "normalization_only_change",
                    "info",
                    "Different source text becomes equal under " + "/".join(forms) + ".",
                    old.location(i, j),
                    new.location(k, end),
                )
            )
    return found


def compare_texts(
    before: str, after: str, *, synthetic_only: bool = False, kind: str = "revision"
) -> QualityReport:
    """Review exact edits via the existing bounded revision comparison service."""
    _guard(synthetic_only, kind)
    _validate(before)
    _validate(after)
    field = revision_comparison.compare_revisions(_snapshot(before), _snapshot(after)).fields[0]
    old, new = _Source(before, "before"), _Source(after, "after")
    return _report(kind, "comparison", (old, new), _compare(old, new, field))


def inspect_revision(
    revision: Revision, *, previous: Revision | None = None, synthetic_only: bool = False
) -> QualityReport:
    """Inspect immutable revision text fields; references and state are never changed."""
    _guard(synthetic_only, "revision")
    # Authoritative validation applies to all fields before any diagnostics are created.
    result = revision_comparison.compare_revisions(
        previous if previous is not None else revision, revision
    )
    sources: list[_Source] = []
    diagnostics: list[Diagnostic] = []
    for field in result.fields:
        new = _Source(
            getattr(revision, field.key),
            "after." + field.key if previous else "source." + field.key,
        )
        if previous is None:
            sources.append(new)
            diagnostics.extend(_inspect(new))
        else:
            old = _Source(getattr(previous, field.key), "before." + field.key)
            sources.extend((old, new))
            diagnostics.extend(_compare(old, new, field))
    return _report(
        "revision", "comparison" if previous else "inspection", tuple(sources), diagnostics
    )
