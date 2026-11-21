"""Bounded character spans on a currently allowed, exact original source.

Offsets are Python Unicode character positions, never UTF-8 bytes or a rewritten
source. They exist only in this read projection and are recomputed on every open.
"""

import re
import unicodedata

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service

from . import policy, services
from .text import fold, normalize, query

MAX_MATCHES = 200


def _normalized_map(original):
    """Map normalized characters to source clusters and verify the whole profile.

    Combining marks stay with their original base, including marks removed from
    the derived profile. Compatibility/casefold expansions retain their one
    original cluster. An unusual composition across cluster boundaries must
    match the whole-string profile before any offset may be used.
    """
    starts = [
        index
        for index, char in enumerate(original)
        if index == 0 or not unicodedata.category(char).startswith("M")
    ]
    output, offsets = [], []
    for start, end in zip(starts, [*starts[1:], len(original)], strict=True):
        for char in fold(original[start:end]):
            if char.isspace():
                if not output:
                    continue
                if output[-1] == " ":
                    offsets[-1] = (offsets[-1][0], end)
                    continue
                char = " "
            output.append(char)
            offsets.append((start, end))
    if output and output[-1] == " ":
        output.pop()
        offsets.pop()
    normalized = "".join(output)
    return (normalized, offsets) if normalized == normalize(original) else None


def project(original, *, value, mode, index=0):
    """Highlight only exact literal/normalized occurrences, even in fuzzy results."""
    cases._text(original)
    _, tokens = query(value, mode)
    if type(index) is not int or not 0 <= index < MAX_MATCHES:
        raise cases.CaseConflict("search_match_position_invalid")
    spans, state = [], "EXACT_LITERAL" if mode == "LITERAL" else "EXACT_NORMALIZED_WORDS"
    if mode == "LITERAL":
        cursor = 0
        while len(spans) <= MAX_MATCHES:
            start = original.find(value, cursor)
            if start < 0:
                break
            cursor = start + len(value)
            spans.append((start, cursor))
    else:
        mapped = _normalized_map(original)
        if mapped is None:
            state = "UNMAPPABLE_NORMALIZATION"
        else:
            normalized, offsets = mapped
            for match in re.finditer(r"[^\W_]+", normalized, re.UNICODE):
                if match.group() not in tokens:
                    continue
                start, end = offsets[match.start()][0], offsets[match.end() - 1][1]
                # One compatibility character can expand into several words.
                # Overlapping source spans are one navigable original passage.
                if spans and start < spans[-1][1]:
                    spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
                else:
                    spans.append((start, end))
                if len(spans) > MAX_MATCHES:
                    break
            if mode == "FUZZY":
                state = (
                    "EXACT_WORDS_IN_APPROXIMATE_RESULT"
                    if spans
                    else "APPROXIMATE_WITHOUT_EXACT_SPAN"
                )
    limited = len(spans) > MAX_MATCHES
    spans = spans[:MAX_MATCHES]
    if index >= max(1, len(spans)):
        raise cases.CaseConflict("search_match_position_invalid")
    matches, parts, cursor = [], [], 0
    for number, (start, end) in enumerate(spans):
        if start > cursor:
            parts.append({"text": original[cursor:start], "matched": False})
        match = {"start": start, "end": end, "text": original[start:end], "number": number + 1}
        matches.append(match)
        parts.append({**match, "matched": True, "active": number == index})
        cursor = end
    if cursor < len(original):
        parts.append({"text": original[cursor:], "matched": False})
    if "".join(part["text"] for part in parts) != original:
        raise cases.CaseConflict("search_match_projection_invalid")
    return {
        "state": state,
        "matches": matches,
        "parts": parts,
        "active": matches[index] if matches else None,
        "index": index,
        "number": index + 1 if matches else 0,
        "count": len(matches),
        "limited": limited,
        "has_previous": bool(matches) and index > 0,
        "has_next": bool(matches) and index + 1 < len(matches),
        "query": value,
        "mode": mode,
    }


def open_in_context(context, *, case_id, generation_id, document_id, value, mode, index=0):
    """A result token locates data; current OPEN and SEARCH grants authorize it."""
    case = context.cases[str(case_id)]
    context.require(case, "OPEN")
    context.require(case, "SEARCH")
    opened = services.open_in_context(
        context, case_id=case_id, generation_id=generation_id, document_id=document_id
    )
    # Recheck real engine membership against this exact current document. A
    # signed query or stale browser page cannot fabricate a matching source.
    rows = services._queryset([opened["document_id"]], value, mode)
    if mode == "FUZZY":
        with services.fuzzy_threshold():
            matched = rows.exists()
    else:
        matched = rows.exists()
    if not matched:
        raise cases.CaseConflict("search_match_not_current")
    return {**opened, "navigation": project(opened["text"], value=value, mode=mode, index=index)}


@mutation_service
def open_match(*, generation_id, document_id, value, mode="FTS", index=0, **base):
    with policy.boundary(**base, action="OPEN") as context:
        return open_in_context(
            context,
            case_id=base["case_id"],
            generation_id=generation_id,
            document_id=document_id,
            value=value,
            mode=mode,
            index=index,
        )
