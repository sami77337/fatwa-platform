"""Owned standalone composition; shared wiring belongs to the coordinator."""

from config.settings.campaign_review import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "apps.pdf_citations"]  # noqa: F405
FATWA_PDF_CITATIONS_ENABLED = False
ROOT_URLCONF = "apps.pdf_citations.urls"
MIDDLEWARE = [
    "apps.pdf_citations.guard.PdfCitationGuard"
    if item == "apps.library_preview.guard.PreviewCompositionGuard"
    else item
    for item in MIDDLEWARE  # noqa: F405
]
