"""Versioned development matching copy. Source text is never normalized in place."""

import json
import re
import unicodedata
from hashlib import sha256

from apps.casework.services import CaseConflict

PROFILE = "ar-simple-trigram-dev-v1"
MODES = {"LITERAL", "FTS", "FUZZY"}
FUZZY_THRESHOLD = "0.35"
_TRANSLATE = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def text_digest(value):
    return sha256(value.encode()).hexdigest()


def normalize(value):
    value = unicodedata.normalize("NFKC", value).translate(_TRANSLATE).casefold()
    value = "".join(c for c in value if c != "ـ" and unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", value).strip()


def query(value, mode):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 120
        or not value.strip()
        or mode not in MODES
        or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)
    ):
        raise CaseConflict("search_query_invalid")
    normalized = normalize(value)
    # Operators are ordinary text, never raw tsquery syntax. A punctuation-only
    # request is rejected instead of silently becoming an unbounded query.
    tokens = tuple(dict.fromkeys(re.findall(r"[^\W_]+", normalized, re.UNICODE)))
    if not tokens or len(tokens) > 8 or (mode == "FUZZY" and any(len(t) < 3 for t in tokens)):
        raise CaseConflict("search_query_invalid")
    return normalized, tokens
