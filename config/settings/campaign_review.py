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
    "apps.source_rights",
    "apps.research_workspace",
    "apps.pilot_workbench",
    "apps.browser_audio",
    "apps.classification_review",
    "apps.timed_citations",
    "apps.pdf_citations",
    "apps.arabic_search_eval",
    "apps.case_assignments",
    "apps.case_organization",
    "apps.content_reports",
    "apps.data_quality",
    "apps.selected_exports",
    "apps.scholarly_links",
    "apps.public_knowledge",
    "apps.research_library",
    "apps.case_lifecycle",
    "apps.public_collections",
    "apps.material_import",
    "django.contrib.postgres",
    "apps.canonical_search",
    "apps.public_answer_media",
    "apps.precise_citations",
    "apps.staff_shell",
    "apps.identity_registry",
    "apps.public_reader_tools",
    "apps.material_api",
    "apps.publication_schedules",
    "apps.publication_destinations",
    "apps.development_taxonomy",
    "apps.public_teaching",
    "apps.operational_workspace",
    "apps.ai_gateway",
    "apps.staff_sessions",
]
FATWA_STAFF_SESSIONS_ENABLED = False
FATWA_STAFF_SESSION_AUTHORITY = None
FATWA_STAFF_SESSION_RUNTIME_EPOCH = None
FATWA_DATA_PRIVACY_ENABLED = False
FATWA_DATA_PRIVACY_AUTHORITY = None
FATWA_OPERATIONAL_WORKSPACE_ENABLED = False
FATWA_OPERATIONAL_WORKSPACE_AUTHORITY = None
FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED = False
FATWA_OPERATIONAL_METADATA_ENABLED = False
FATWA_OPERATIONAL_LESSON_LINKS_ENABLED = False
FATWA_OPERATIONAL_COORDINATION_ENABLED = False
FATWA_OPERATIONAL_TRANSCRIPTS_ENABLED = False
FATWA_OPERATIONAL_PUBLICATION_ENABLED = False
FATWA_OPERATIONAL_PRIORITY_POLICY = None
FATWA_AI_GATEWAY_ENABLED = False
FATWA_AI_CITATION_CANDIDATES_ENABLED = False
FATWA_AI_GATEWAY_AUTHORITY = None
FATWA_AI_CITATION_PROVIDER = None
FATWA_AI_DISABLED_PROVIDERS = frozenset()
FATWA_PUBLIC_READER_TOOLS_ENABLED = False
FATWA_PUBLIC_READER_TOOLS_AUTHORITY = None
FATWA_REFERENCE_LOOKUP_ENABLED = False
FATWA_PUBLIC_FATWA_REFERENCES = None
FATWA_STAFF_PWA_ENABLED = False
FATWA_PRECISE_CITATIONS_ENABLED = False
FATWA_PRECISE_CITATIONS_AUTHORITY = None
FATWA_PUBLIC_ANSWER_MEDIA_ENABLED = False
FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED = False
FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY = None
FATWA_CANONICAL_SEARCH_ENABLED = False
FATWA_SEARCH_GOVERNANCE_ENABLED = False
FATWA_CANONICAL_SEARCH_AUTHORITY = None
FATWA_MATERIAL_IMPORT_ENABLED = False
FATWA_MATERIAL_IMPORT_AUTHORITY = None
FATWA_MATERIAL_IMPORT_TTL_SECONDS = 1800
FATWA_PUBLIC_COLLECTIONS_ENABLED = False
FATWA_PUBLIC_COLLECTIONS_AUTHORITY = None
FATWA_CASE_LIFECYCLE_ENABLED = False
FATWA_CASE_LIFECYCLE_AUTHORITY = None
FATWA_RESEARCH_LIBRARY_ENABLED = False
FATWA_RESEARCH_LIBRARY_PUBLIC_ENABLED = False
FATWA_RESEARCH_LIBRARY_OFFLINE_ENABLED = False
FATWA_RESEARCH_LIBRARY_AUTHORITY = None
FATWA_PUBLIC_KNOWLEDGE_ENABLED = False
FATWA_PUBLIC_KNOWLEDGE_AUTHORITY = None
FATWA_PUBLIC_KNOWLEDGE_LANGUAGES = {"ar": "العربية"}
FATWA_PUBLIC_KNOWLEDGE_ORIGIN = ""
FATWA_DATA_QUALITY_ENABLED = False
FATWA_SCHOLARLY_LINKS_ENABLED = False
FATWA_SCHOLARLY_LINKS_AUTHORITY = None
FATWA_SELECTED_EXPORTS_ENABLED = False
FATWA_SELECTED_EXPORTS_AUTHORITY = None
FATWA_SELECTED_EXPORTS_TTL_SECONDS = 1800
FATWA_SELECTED_EXPORTS_LEASE_SECONDS = 120
FATWA_CASE_ASSIGNMENTS_ENABLED = False
FATWA_CASE_ASSIGNMENT_CANDIDATES = None
FATWA_CASE_ORGANIZATION_ENABLED = False
FATWA_RESEARCH_COLLECTIONS_ENABLED = False
FATWA_CONTENT_REPORTS_ENABLED = False
FATWA_CONTENT_REPORTS_AUTHORITY = None
FATWA_ARABIC_SEARCH_EVAL_ENABLED = False
FATWA_ARABIC_SEARCH_REVIEW_ENABLED = False
FATWA_ARABIC_SEARCH_REVIEW_AUTHORITY = None
FATWA_CANONICAL_BENCHMARK_ENABLED = False
FATWA_CANONICAL_BENCHMARK_AUTHORITY = None
FATWA_TIMED_CITATIONS_ENABLED = False
FATWA_PDF_CITATIONS_ENABLED = False
FATWA_BROWSER_AUDIO_ENABLED = False
FATWA_CLASSIFICATION_REVIEW_ENABLED = False
FATWA_CLASSIFICATION_REVIEW_AUTHORITY = None
FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED = False
FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_POLICY = None
# Explicit, separate opt-ins for the closed synthetic V7 workflow.
FATWA_CASE_ATTACHMENTS_ENABLED = False
FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED = False
FATWA_CASE_CITATIONS_ENABLED = False
FATWA_ANSWER_MEDIA_ENABLED = False
FATWA_ANSWER_MEDIA_PRIVATE_ENABLED = False
FATWA_MEDIA_STORAGE_MIGRATION_ENABLED = False
FATWA_SOURCE_CASE_INTAKE_ENABLED = False
FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED = False
FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED = False
FATWA_SOURCE_RIGHTS_ENABLED = False
FATWA_SOURCE_RIGHTS_AUTHORITY = None
# V11 explicitly requires current source grants; older isolated profiles retain
# their historical contract until the complete V11 composition is selected.
FATWA_SOURCE_RIGHTS_ENFORCED = False
FATWA_RESEARCH_WORKSPACE_ENABLED = False
FATWA_RESEARCH_WORKSPACE_RIGHTS = None
FATWA_PILOT_WORKBENCH_ENABLED = False
FATWA_PILOT_WORKBENCH = None
FATWA_RECOVERY_MAINTENANCE_REQUIRED = False
FATWA_RECOVERY_MAINTENANCE_ROOT = None
# Recovery never defaults to plaintext; legacy V10 uses a separate test module.
FATWA_RECOVERY_ENCRYPTION_REQUIRED = True
FATWA_RECOVERY_V10_TEST_COMPAT = False
FATWA_KNOWLEDGE_LINKS_ENABLED = False
FATWA_KNOWLEDGE_LINKS_AUTHORITY = None
FATWA_COMPOSITE_DELIVERY_ENABLED = False
FATWA_COMPOSITE_CHOICES_ENABLED = False
FATWA_COMPOSITE_RETRY_ENABLED = False
FATWA_COMPOSITE_PUBLICATION_PROPOSAL_ENABLED = False
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
# Native multi-select question types plus exact version/CSRF fields remain bounded.
# The native taxonomy forms have bounded repeated node/mapping fields (at most
# 456 valid submitted fields); each handler still validates its exact schema.
# Keep the existing byte budget independently enforced by CaseworkGuard.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 512

# One shared composition; optional profile aliases reuse these same overlays.
TEMPLATES = deepcopy(TEMPLATES)  # noqa: F405
TEMPLATES[0]["OPTIONS"]["context_processors"].append(
    "apps.requester_team_journey.context.connected_navigation"
)
TEMPLATES[0]["OPTIONS"]["context_processors"].append("apps.mufti_workspace.context.case_workspace")
TEMPLATES[0]["OPTIONS"]["context_processors"].append("apps.browser_audio.context.capture")
TEMPLATES[0]["OPTIONS"]["context_processors"].append("apps.case_organization.context.organization")
TEMPLATES[0]["OPTIONS"]["context_processors"].append("apps.scholarly_links.context.scholarly_links")
TEMPLATES[0]["OPTIONS"]["context_processors"].append("apps.staff_shell.context.installable_staff")
TEMPLATES[0]["DIRS"] = [
    Path(__file__).resolve().parents[2] / "apps/transcript_case_links/templates",
    Path(__file__).resolve().parents[2] / "apps/requester_team_journey/templates",
    *TEMPLATES[0]["DIRS"],
]
MIDDLEWARE = [
    "apps.platform_recovery.middleware.MaintenanceGuard",
    "apps.staff_sessions.middleware.SessionContext",
    "apps.material_api.middleware.MaterialAPIResponses",
    "apps.private_media.links.PrivateMediaResponses",
    *[
        "apps.library_preview.guard.PreviewCompositionGuard"
        if item == "apps.casework_web.guard.CaseworkGuard"
        else item
        for item in MIDDLEWARE  # noqa: F405
    ],
]
FATWA_ANSWER_LINKS_ENABLED = False
FATWA_ANSWER_RELATED_ENABLED = False

# Temporary private locators need explicit independent signing configuration.
FATWA_PRIVATE_MEDIA_LINKS_ENABLED = False
FATWA_PRIVATE_MEDIA_LINKS_KEY = None
FATWA_PRIVATE_MEDIA_LINKS_EPOCH = None
FATWA_PRIVATE_MEDIA_LINKS_TTL_SECONDS = None

FATWA_IDENTITY_REGISTRY_ENABLED = False
FATWA_IDENTITY_REGISTRY_AUTHORITY = None

# Read-only allowed-material API; separate from privileged integrations.
FATWA_MATERIAL_API_ENABLED = False

FATWA_PUBLICATION_SCHEDULES_ENABLED = False
FATWA_PUBLICATION_SCHEDULES_AUTHORITY = None

FATWA_PUBLICATION_DESTINATIONS_ENABLED = False
FATWA_PUBLICATION_DESTINATIONS_AUTHORITY = None
FATWA_PUBLICATION_DESTINATION_PROFILES = None
FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER = None

FATWA_DEVELOPMENT_TAXONOMY_ENABLED = False
FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY = None

FATWA_PUBLIC_TEACHING_ENABLED = False
FATWA_PUBLIC_TEACHING_PUBLIC_ENABLED = False
FATWA_PUBLIC_TEACHING_AUTHORITY = None
