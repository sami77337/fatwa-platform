"""Small Arabic query equivalences for staff case search only.

Never normalize stored source text, citation identifiers, or book headings with this.
"""
import re

from apps.reference.normalization import normalize_title

_EQUIVALENT = {"بدون": "بلا", "دون": "بلا", "بلا": "بلا"}
_WORD = re.compile(r"(?u)\w+")


def normalize_case_search(value: str) -> str:
    """Normalize a query candidate without modifying the original value."""
    normalized = normalize_title(value)
    return _WORD.sub(lambda m: _EQUIVALENT.get(m.group(), m.group()), normalized)


def case_search_matches(query: str, *fields: str) -> bool:
    """Keep phrase matching and equate the negative prepositions as whole words."""
    needle = normalize_case_search(query)
    return not needle or any(needle in normalize_case_search(field) for field in fields)
