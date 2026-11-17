"""Small Arabic query equivalences for staff case search only.

Never normalize stored source text, citation identifiers, or book headings with this.
"""
import re

from apps.editorial_search.query_terms import synonym_pattern
from apps.reference.normalization import normalize_title

# Bare "دون" can mean "less than" in jurisprudential questions; do not conflate it.
_EQUIVALENT = {"بدون": "بلا", "بلا": "بلا"}
_WORD = re.compile(r"(?u)\w+")


def normalize_case_search(value: str) -> str:
    """Normalize a query candidate without modifying the original value."""
    normalized = normalize_title(value)
    return _WORD.sub(lambda m: _EQUIVALENT.get(m.group(), m.group()), normalized)


def case_search_matches(query: str, *fields: str) -> bool:
    """Keep phrase matching and equate the negative prepositions as whole words."""
    needle = normalize_case_search(query)
    literal = normalize_title(query)
    if not literal or any(literal in normalize_title(field) for field in fields):
        return True
    pattern = synonym_pattern(needle)
    return any(pattern.search(normalize_case_search(field)) is not None for field in fields)
