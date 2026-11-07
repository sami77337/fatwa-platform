"""Local synthetic reviewer. Configure the SHA-256 of a secrets.token_hex(32) ASCII string."""

import os
import re
from hashlib import sha256
from hmac import compare_digest

from apps.editorial_export.services import require_development


def authenticate_fixture_reviewer(token: str) -> str:
    """Return the fixed fixture principal only on proof of its configured random token."""
    require_development(synthetic_fixtures_only=True)
    expected = os.environ.get("FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256", "")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected)
        or not isinstance(token, str)
        or not re.fullmatch(r"[0-9a-f]{64}", token)
        or not compare_digest(sha256(token.encode("ascii")).hexdigest(), expected)
    ):
        raise ValueError("fixture_reviewer_authentication_failed")
    return "synthetic-reviewer"
