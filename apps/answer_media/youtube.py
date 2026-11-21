"""Descriptive external references only: validate a URL, never contact its host."""

import re
from dataclasses import dataclass
from hashlib import sha256

from apps.casework import services as cases

KIND = "YOUTUBE_LINK"
MIME = "text/uri-list"
URL = re.compile(
    r"https://(?:(?:www\.)?youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})\Z", re.ASCII
)


@dataclass(frozen=True)
class ExternalLink:
    raw: bytes
    sha256: str
    size: int
    filename: str
    media_type: str
    metadata: dict


def validate(url, label):
    if (
        type(url) is not str
        or type(label) is not str
        or not 1 <= len(label) <= 200
        or not label.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in label)
    ):
        raise cases.CaseConflict("youtube_link_invalid")
    matched = URL.fullmatch(url)
    if matched is None:
        raise cases.CaseConflict("youtube_link_invalid")
    video_id = matched.group(1)
    raw = url.encode("UTF-8")
    return ExternalLink(
        raw=raw,
        sha256=sha256(raw).hexdigest(),
        size=len(raw),
        filename=f"youtube-{video_id}.url",
        media_type=MIME,
        metadata={
            "external": True,
            "provider": "YOUTUBE",
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "label": label,
            "availability": "UNVERIFIED",
        },
    )


def verify(row, raw):
    try:
        expected = validate(raw.decode("UTF-8"), row.metadata.get("label"))
    except (UnicodeError, AttributeError, cases.CaseConflict) as exc:
        raise cases.CaseConflict("youtube_link_integrity") from exc
    if (
        row.kind != KIND
        or row.storage_backend != "inline-database-v1"
        or row.filename != expected.filename
        or row.media_type != expected.media_type
        or row.sha256 != expected.sha256
        or row.size != expected.size
        or row.metadata != expected.metadata
    ):
        raise cases.CaseConflict("youtube_link_integrity")
    return expected
