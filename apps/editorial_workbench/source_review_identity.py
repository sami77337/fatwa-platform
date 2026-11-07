"""Independent credentials for the two local synthetic staff identities."""

import os
import re
from hashlib import sha256
from hmac import compare_digest

from apps.editorial_export.services import require_development

ROLE_CREDENTIALS = {
    "reviewer": "FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256",
    "author": "FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256",
}


def credential_digest(role):
    digest = os.environ.get(ROLE_CREDENTIALS[role], "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return ""
    if role == "author" and digest == os.environ.get(ROLE_CREDENTIALS["reviewer"]):
        return ""
    return digest


def authenticate_fixture_role(token, role):
    require_development(synthetic_fixtures_only=True)
    expected = credential_digest(role)
    if not expected or not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError(f"fixture_{role}_authentication_failed")
    if not compare_digest(sha256(token.encode("ascii")).hexdigest(), expected):
        raise ValueError(f"fixture_{role}_authentication_failed")
    return "synthetic-mufti-author" if role == "author" else "synthetic-reviewer"


def authenticate_fixture_reviewer(token: str) -> str:
    return authenticate_fixture_role(token, "reviewer")
