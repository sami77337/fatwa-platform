"""Opt-in synthetic requester/team journey; all casework gates remain closed."""

from copy import deepcopy
from pathlib import Path

from .casework_review import *  # noqa: F403

INSTALLED_APPS = [
    *INSTALLED_APPS,  # noqa: F405
    "apps.requester_access_review.apps.RequesterAccessReviewConfig",
    "apps.team_updates.apps.TeamUpdatesConfig",
    "apps.case_delivery_desk",
    "apps.transcript_case_links.apps.TranscriptCaseLinksConfig",
]
FATWA_CASE_DELIVERY_APPROVAL_VERIFIER = None
FATWA_CASE_DELIVERY_PROVIDER_VERIFIER = None
# Explicit synthetic-only policy opt-in; approvals alone never reveal private answers.
FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED = False
ROOT_URLCONF = "config.campaign_urls"
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = 262144
DATA_UPLOAD_MAX_NUMBER_FILES = 1

# One shared composition; optional profile aliases reuse these same overlays.
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]["DIRS"] = [
    Path(__file__).resolve().parents[2] / "apps/transcript_case_links/templates",
    Path(__file__).resolve().parents[2] / "apps/requester_team_journey/templates",
    *TEMPLATES[0]["DIRS"],
]
