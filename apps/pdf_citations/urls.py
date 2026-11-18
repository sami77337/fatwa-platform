"""Test-only composition; integrator installs actions and guarded GET explicitly."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import ACTIONS, document, review_document, workspace


def staff(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    from apps.requester_team_journey.views import staff as existing

    return existing(request)


urlpatterns = [
    path("casework/staff/", staff),
    path(
        "casework/staff/pdf-citations/<uuid:citation_id>/document/", document, name="pdf_document"
    ),
    path(
        "casework/staff/pdf-citations/<uuid:citation_id>/review-document/",
        review_document,
        name="pdf_review_document",
    ),
    *campaign_patterns,
]
