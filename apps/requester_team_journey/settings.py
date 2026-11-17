"""Opt-in loopback profile; keep every upstream gate and identity requirement."""
from copy import deepcopy
from pathlib import Path

from apps.requester_access_review.settings import *  # noqa: F403

ROOT_URLCONF = "apps.requester_team_journey.urls"
# Django's same-name template inheritance skips the extending template's origin,
# so these tiny overlays reuse the original templates without copying or editing them.
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]["DIRS"] = [Path(__file__).resolve().parent / "templates", *TEMPLATES[0]["DIRS"]]
