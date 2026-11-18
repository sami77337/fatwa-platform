"""Narrow pg_dump equivalence over SQL tokens; quoted bytes are never rewritten.

This is not a general SQL parser or formatter. Unsupported expressions are left
byte-for-byte intact, so a restore may fail closed instead of weakening its hash.
Only the observed varchar-literal-array -> text[] deparser equivalence is handled.
"""

import re
from dataclasses import dataclass


class SchemaLexicalError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int


NONCE = re.compile(r"\\(?:un)?restrict [A-Za-z0-9_]+(?:\r\n|\r|\n|$)")
SPACE = " \t\r\n\f\v"


def _identifier_start(char):
    return char == "_" or char.isalpha() or ord(char) >= 128


def _identifier_part(char):
    return _identifier_start(char) or char.isdigit() or char == "$"


def _quoted_end(raw, start, quote, *, escape=False):
    i = start + 1
    while i < len(raw):
        if escape and raw[i] == "\\":
            i += 2
        elif raw[i] == quote:
            if i + 1 < len(raw) and raw[i + 1] == quote:
                i += 2
            else:
                return i + 1
        else:
            i += 1
    raise SchemaLexicalError("unterminated_quoted_token")


def tokens(raw):
    """Lex standard-conforming pg_dump SQL, retaining all original source spans."""
    i = 0
    while i < len(raw):
        start = i
        kind = "symbol"
        nonce = NONCE.match(raw, i) if i == 0 or raw[i - 1] in "\r\n" else None
        if nonce:
            i, kind = nonce.end(), "nonce"
        elif raw[i] in SPACE:
            i += 1
            while i < len(raw) and raw[i] in SPACE:
                i += 1
            kind = "space"
        elif raw.startswith("--", i):
            i += 2
            while i < len(raw) and raw[i] not in "\r\n":
                i += 1
            kind = "comment"
        elif raw.startswith("/*", i):
            depth, i = 1, i + 2
            while i < len(raw) and depth:
                if raw.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif raw.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise SchemaLexicalError("unterminated_comment")
            kind = "comment"
        elif raw[i] in "eE" and raw[i + 1 : i + 2] == "'":
            i, kind = _quoted_end(raw, i + 1, "'", escape=True), "string"
        elif raw[i : i + 2].upper() == "U&" and raw[i + 2 : i + 3] in ("'", '"'):
            quote = raw[i + 2]
            i, kind = _quoted_end(raw, i + 2, quote), "unicode_quoted"
        elif raw[i] in "'\"":
            quote = raw[i]
            i, kind = _quoted_end(raw, i, quote), "string" if quote == "'" else "identifier"
        elif raw[i] == "$":
            end = i + 1
            if end < len(raw) and _identifier_start(raw[end]):
                end += 1
                while end < len(raw) and raw[end] != "$" and _identifier_part(raw[end]):
                    end += 1
            if end < len(raw) and raw[end] == "$":
                tag = raw[i : end + 1]
                close = raw.find(tag, end + 1)
                if close < 0:
                    raise SchemaLexicalError("unterminated_dollar_quote")
                i, kind = close + len(tag), "dollar_quoted"
            else:
                i += 1
        elif _identifier_start(raw[i]):
            i += 1
            while i < len(raw) and _identifier_part(raw[i]):
                i += 1
            kind = "word"
        elif raw.startswith("::", i):
            i += 2
        else:
            i += 1
        yield Token(kind, raw[start:i], start, i)


def _is(token, text):
    kind = "word" if text[0].isalpha() else "symbol"
    return token.kind == kind and token.text.upper() == text.upper()


def _matches(items, index, sequence):
    return index + len(sequence) <= len(items) and all(
        _is(items[index + offset], text) for offset, text in enumerate(sequence)
    )


def _closing_paren(items, opening):
    depth = 0
    for index in range(opening, len(items)):
        if _is(items[index], "("):
            depth += 1
        elif _is(items[index], ")"):
            depth -= 1
            if depth == 0:
                return index
    return None


def _expression_ranges(items):
    """Only real CHECK constraint bodies or top-level partial-index predicates."""
    index_prefix = _matches(items, 0, ("CREATE", "INDEX")) or _matches(
        items, 0, ("CREATE", "UNIQUE", "INDEX")
    )
    if index_prefix:
        depth = 0
        for index, item in enumerate(items):
            if _is(item, "("):
                depth += 1
            elif _is(item, ")"):
                depth -= 1
            elif depth == 0 and _is(item, "WHERE"):
                yield index + 1, len(items)
                return
    table_prefix = any(
        _matches(items, 0, prefix)
        for prefix in (
            ("CREATE", "TABLE"),
            ("CREATE", "UNLOGGED", "TABLE"),
            ("ALTER", "TABLE"),
            # A constraint fragment is also used by the focused deparser tests.
            ("CONSTRAINT",),
        )
    )
    if table_prefix:
        for index in range(len(items) - 3):
            if (
                _is(items[index], "CONSTRAINT")
                and items[index + 1].kind in ("word", "identifier", "unicode_quoted")
                and _matches(items, index + 2, ("CHECK", "("))
            ):
                close = _closing_paren(items, index + 3)
                if close is not None:
                    yield index + 4, close


def _array_cast(items, start, limit, raw):
    """Recognize one complete cast expression; never inspect string contents."""
    if not _matches(items, start, ("(", "ARRAY", "[")):
        return None
    cursor, elements = start + 3, []
    while cursor < limit:
        if items[cursor].kind != "string" or not _matches(
            items, cursor + 1, ("::", "character", "varying")
        ):
            return None
        end = cursor + 4
        if end > limit:
            return None
        # The literal and its varchar cast are copied, not decoded or formatted.
        elements.append(raw[items[cursor].start : items[end - 1].end])
        cursor = end
        if cursor < limit and _is(items[cursor], ","):
            cursor += 1
            continue
        break
    suffix = ("]", ")", "::", "text", "[", "]")
    if not elements or cursor + len(suffix) > limit or not _matches(items, cursor, suffix):
        return None
    return cursor + len(suffix), "ARRAY[" + ", ".join(
        "(" + value + ")::text" for value in elements
    ) + "]"


def canonical_schema(raw):
    lexed = list(tokens(raw))
    edits = [(item.start, item.end, "") for item in lexed if item.kind == "nonce"]
    opaque = [item for item in lexed if item.kind in ("comment", "nonce")]
    statement = []

    def normalize(items):
        for lower, upper in _expression_ranges(items):
            cursor = lower
            while cursor < upper:
                found = _array_cast(items, cursor, upper, raw)
                if found is None:
                    cursor += 1
                    continue
                end, replacement = found
                start_offset, end_offset = items[cursor].start, items[end - 1].end
                # Comments are meaningful source, and are never dropped by folding.
                if not any(start_offset <= item.start < end_offset for item in opaque):
                    edits.append((start_offset, end_offset, replacement))
                cursor = end

    for item in lexed:
        if item.kind in ("space", "comment", "nonce"):
            continue
        if _is(item, ";"):
            normalize(statement)
            statement = []
        else:
            statement.append(item)
    normalize(statement)
    result, previous = [], 0
    for start, end, replacement in sorted(edits):
        if start < previous:
            raise SchemaLexicalError("overlapping_schema_edit")
        result.extend((raw[previous:start], replacement))
        previous = end
    result.append(raw[previous:])
    return "".join(result).encode()
