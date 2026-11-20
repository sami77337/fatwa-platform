"""The existing media parser plus a bounded, pipe-only video decoding worker."""

import json
import os
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from apps.private_media.validation import MediaValidationError, ValidatedMedia, validate


def validate_file(raw, filename, media_type):
    if media_type not in {"video/webm", "video/mp4"}:
        return validate(raw, filename, media_type)
    extension = {"video/webm": "webm", "video/mp4": "mp4"}[media_type]
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= 192000
        or type(filename) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,94}\." + extension, filename) is None
    ):
        raise MediaValidationError("library_video_input_invalid")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "apps.research_library.video_worker", extension],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            cwd=Path(__file__).resolve().parents[2],
            env={
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        if result.returncode or len(result.stdout) > 4096:
            raise ValueError
        metadata = json.loads(result.stdout)
        if metadata.get("validated") is not True or metadata.get("kind") != "video":
            raise ValueError
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        raise MediaValidationError("library_video_content_invalid") from exc
    return ValidatedMedia(
        raw, filename, media_type, sha256(raw).hexdigest(), len(raw), "video", metadata
    )
