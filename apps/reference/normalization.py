"""Conservative Arabic SEARCH normalization; original titles stay unchanged."""
import re
import unicodedata

_TRANSLATE = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})


def normalize_title(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    value = "".join(
        char for char in value if char != "ـ" and unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", value).strip()
