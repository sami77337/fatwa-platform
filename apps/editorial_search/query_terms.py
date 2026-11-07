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
