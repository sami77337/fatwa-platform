"""Navigation visibility only; every destination enforces its own independent gate."""

from django.apps import apps
from django.conf import settings


def connected_navigation(request):
    return {
        "public_knowledge_navigation": apps.is_installed("apps.public_knowledge")
        and getattr(settings, "FATWA_PUBLIC_KNOWLEDGE_ENABLED", False) is True,
        "selected_exports_navigation": apps.is_installed("apps.selected_exports")
        and getattr(settings, "FATWA_SELECTED_EXPORTS_ENABLED", False) is True,
        "quality_navigation": request.path.startswith("/casework/staff/")
        and apps.is_installed("apps.data_quality")
        and getattr(settings, "FATWA_DATA_QUALITY_ENABLED", False) is True,
        "classification_navigation": request.path == "/casework/staff/"
        and apps.is_installed("apps.classification_review")
        and getattr(settings, "FATWA_CLASSIFICATION_REVIEW_ENABLED", False) is True,
        "library_preview_navigation": apps.is_installed("apps.library_preview")
        and getattr(settings, "FATWA_LIBRARY_PREVIEW_ENABLED", False) is True,
        "source_desk_navigation": request.path == "/casework/staff/"
        and getattr(settings, "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED", False) is True,
    }
