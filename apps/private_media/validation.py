"""Parse uploaded media in a bounded isolated process before retaining exact original bytes."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256

MAX_BYTES = 192000
TEXT_MAX_BYTES = 65536
TYPES = {
    ".txt": ("text/plain", "text"),
    ".pdf": ("application/pdf", "pdf"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".png": ("image/png", "image"),
    ".webp": ("image/webp", "image"),
    ".mp3": ("audio/mpeg", "audio"),
    ".m4a": ("audio/mp4", "audio"),
    ".wav": ("audio/wav", "audio"),
}
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,94}\.[A-Za-z0-9]{2,4}", re.ASCII)
ALIASES = {"audio/x-wav": "audio/wav", "audio/wave": "audio/wav", "audio/x-m4a": "audio/mp4"}


class MediaValidationError(ValueError):
    """Fixed rejection code, never parser diagnostics or file content."""


@dataclass(frozen=True)
class ValidatedMedia:
    raw: bytes
    filename: str
    media_type: str
    sha256: str
    size: int
    kind: str
    metadata: dict


def validate(raw: bytes, filename: str, media_type: str) -> ValidatedMedia:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise MediaValidationError("media_size_invalid")
    if type(filename) is not str or _FILENAME.fullmatch(filename) is None:
        raise MediaValidationError("media_filename_invalid")
    extension = "." + filename.rsplit(".", 1)[-1].lower()
    expected = TYPES.get(extension)
    if expected is None or ALIASES.get(media_type, media_type) != expected[0]:
        raise MediaValidationError("media_type_invalid")
    if extension == ".txt" and len(raw) > TEXT_MAX_BYTES:
        raise MediaValidationError("media_size_invalid")
    request = json.dumps({"raw": base64.b64encode(raw).decode("ascii"), "extension": extension})
    try:
        result = subprocess.run(
            [sys.executable, "-m", "apps.private_media.worker"],
            input=request,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=6,
            check=False,
            cwd=Path(__file__).resolve().parents[2],
            env={
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
            },
        )
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise ValueError
        metadata = json.loads(result.stdout)
        if type(metadata) is not dict or metadata.get("validated") is not True:
            raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise MediaValidationError("media_content_invalid") from exc
    return ValidatedMedia(
        raw, filename, expected[0], sha256(raw).hexdigest(), len(raw), expected[1], metadata
    )
