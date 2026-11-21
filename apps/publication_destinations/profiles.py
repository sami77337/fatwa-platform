"""Fixed server capabilities; a browser cannot create destinations or public URLs."""

from dataclasses import asdict, dataclass
from hashlib import sha256

from django.conf import settings

from apps.casework import services as cases
from apps.delivery_queue.services import _canonical

LABELS = {"WEBSITE": "الموقع", "TELEGRAM_CHANNEL": "قناة تيليجرام"}


@dataclass(frozen=True, slots=True)
class DestinationProfile:
    key: str
    revision: str
    max_chars: int
    mode: str = "SYNTHETIC_ONLY"
    content: str = "REVIEWED_PUBLIC_EDITION"


def payload(profile):
    if (
        not isinstance(profile, DestinationProfile)
        or type(profile.key) is not str
        or profile.key not in LABELS
        or type(profile.revision) is not str
        or not 1 <= len(profile.revision) <= 64
        or not profile.revision.isascii()
        or any(not (c.isalnum() or c in "._:-") for c in profile.revision)
        or type(profile.max_chars) is not int
        or not 1 <= profile.max_chars <= 24000
        or profile.mode != "SYNTHETIC_ONLY"
        or profile.content != "REVIEWED_PUBLIC_EDITION"
    ):
        raise cases.CaseConflict("destination_profile_invalid")
    return asdict(profile)


def configured():
    value = getattr(settings, "FATWA_PUBLICATION_DESTINATION_PROFILES", None)
    if type(value) is not tuple or not 1 <= len(value) <= 2:
        raise cases.CaseConflict("destination_profiles_required")
    result = {item["key"]: item for item in (payload(p) for p in value)}
    if len(result) != len(value):
        raise cases.CaseConflict("destination_profiles_duplicate")
    return result


def fingerprint(value):
    return sha256(_canonical(value)).hexdigest()
