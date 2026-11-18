"""Rank already-authorized title metadata. This module confers no permission."""

import re
from collections import Counter
from dataclasses import dataclass

from apps.reference.normalization import normalize_title

VERSION = "arabic-title-words-v2-capacity64"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TOKEN = re.compile(r"\d+(?:[.,٫]\d+)*|[^\W\d_]+", re.UNICODE)


def tokens(text: str) -> tuple[str, ...]:
    """Shared normalization + digit folding; preserve ة/ه and ؤ/ئ/ء."""
    return tuple(_TOKEN.findall(normalize_title(text).translate(_DIGITS)))


def query_tokens(query: str) -> tuple[str, ...]:
    if (
        type(query) is not str
        or len(query) > 80
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in query)
    ):
        raise ValueError("invalid_search_query")
    result = tokens(query)
    if not result or len(result) > 10:
        raise ValueError("invalid_search_query")
    return result


@dataclass(frozen=True)
class Candidate:
    identifier: str
    title: str


@dataclass(frozen=True)
class Hit:
    identifier: str
    tier: int
    reason: str


def rank_titles(query: str, candidates: list[Candidate], *, limit: int = 20) -> list[Hit]:
    """Literal title, normalized title, phrase, then all words; stable input ties.

    No substring, stemming, semantic inference, or automatic citation. A numeric
    decimal stays one token, so query 12 does not match 112 or 12.5.
    """
    wanted = query_tokens(query)
    if type(limit) is not int or not 1 <= limit <= 64 or len(candidates) > 64:
        raise ValueError("invalid_candidate_window")
    seen, ranked = set(), []
    for index, candidate in enumerate(candidates):
        if (
            not isinstance(candidate, Candidate)
            or type(candidate.identifier) is not str
            or not candidate.identifier
            or candidate.identifier in seen
            or type(candidate.title) is not str
            or len(candidate.title) > 2000
        ):
            raise ValueError("invalid_candidate")
        seen.add(candidate.identifier)
        words = tokens(candidate.title)
        if Counter(wanted) - Counter(words):
            continue
        if candidate.title.strip() == query.strip():
            tier, reason = 0, "literal_title"
        elif words == wanted:
            tier, reason = 1, "normalized_title"
        elif any(words[i : i + len(wanted)] == wanted for i in range(len(words))):
            tier, reason = 2, "contiguous_words"
        else:
            tier, reason = 3, "all_words"
        ranked.append((tier, index, Hit(candidate.identifier, tier, reason)))
    return [hit for _, _, hit in sorted(ranked)[:limit]]
