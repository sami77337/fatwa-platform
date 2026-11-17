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
    "apps.case_attachments",
    "apps.case_citations",
    "apps.experimental_publication",
    "apps.source_case_intake",
    "apps.knowledge_links",
    "apps.composite_delivery",
    "apps.library_preview",
    "apps.requester_portal",
    "apps.mufti_workspace",
]
# Explicit, separate opt-ins for the closed synthetic V7 workflow.
FATWA_CASE_ATTACHMENTS_ENABLED = False
FATWA_CASE_CITATIONS_ENABLED = False
FATWA_ANSWER_MEDIA_ENABLED = False
FATWA_ANSWER_MEDIA_PRIVATE_ENABLED = False
FATWA_MEDIA_STORAGE_MIGRATION_ENABLED = False
FATWA_SOURCE_CASE_INTAKE_ENABLED = False
FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED = False
FATWA_KNOWLEDGE_LINKS_ENABLED = False
FATWA_KNOWLEDGE_LINKS_AUTHORITY = None
FATWA_COMPOSITE_DELIVERY_ENABLED = False
FATWA_COMPOSITE_DELIVERY_CAPABILITIES = None
FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER = None
FATWA_MUFTI_WORKSPACE_ENABLED = False
FATWA_REQUESTER_PORTAL_ENABLED = False
FATWA_LIBRARY_PREVIEW_ENABLED = False
FATWA_LIBRARY_PREVIEW_POLICY = None
FATWA_EXPERIMENTAL_PUBLICATION_ENABLED = False
FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY = None
FATWA_CASE_DELIVERY_APPROVAL_VERIFIER = None
FATWA_CASE_DELIVERY_PROVIDER_VERIFIER = None
# One-time recovery requires an independent, server-configured identity verifier.
FATWA_CASEWORK_RECOVERY_AUTHORITY = None
# Explicit synthetic-only policy opt-in; approvals alone never reveal private answers.
FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED = False
ROOT_URLCONF = "config.campaign_urls"
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = 262144
DATA_UPLOAD_MAX_NUMBER_FILES = 1

# One shared composition; optional profile aliases reuse these same overlays.
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]["OPTIONS"]["context_processors"].append(
    "apps.requester_team_journey.context.connected_navigation"
)
TEMPLATES[0]["OPTIONS"]["context_processors"].append(
    "apps.mufti_workspace.context.case_workspace"
)
TEMPLATES[0]["DIRS"] = [
    Path(__file__).resolve().parents[2] / "apps/transcript_case_links/templates",
    Path(__file__).resolve().parents[2] / "apps/requester_team_journey/templates",
    *TEMPLATES[0]["DIRS"],
]
MIDDLEWARE = [
    "apps.library_preview.guard.PreviewCompositionGuard"
    if item == "apps.casework_web.guard.CaseworkGuard"
    else item
    for item in MIDDLEWARE  # noqa: F405
]
