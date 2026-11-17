"""Search-only Arabic query equivalence; preserve all stored strings and identities."""
import re

from apps.reference.normalization import normalize_title

# Avoid treating standalone "دون" (which can mean "less than") as "without".
_PREPOSITIONS = {"بلا": "بلا", "بدون": "بلا"}
_WORD = re.compile(r"(?u)\w+")


def normalize_editorial_search(text: str) -> str:
    """Normalize a temporary search copy, never a source or reference record."""
    normalized = normalize_title(text)
    return _WORD.sub(lambda m: _PREPOSITIONS.get(m.group(), m.group()), normalized)


def synonym_pattern(text: str) -> re.Pattern:
    """Whole alias words; retain the existing substring behavior of other text."""
    normalized = normalize_editorial_search(text)
    parts, end = [], 0
    for match in _WORD.finditer(normalized):
        parts.append(re.escape(normalized[end:match.start()]))
        word = re.escape(match.group())
        parts.append(r"(?<!\w)" + word + r"(?!\w)" if match.group() == "بلا" else word)
        end = match.end()
    parts.append(re.escape(normalized[end:]))
    return re.compile("".join(parts))
