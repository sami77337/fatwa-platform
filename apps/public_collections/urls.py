"""Owned temporary integration. Final proof uses config.campaign_urls itself."""

from django.urls import include, path

from apps.requester_team_journey.views import staff as campaign_staff
from config.campaign_urls import urlpatterns as campaign_patterns

from . import editor


def staff(request):
    if request.method == "POST" and request.POST.get("action") in editor.ACTIONS:
        return editor.workspace(request)
    return campaign_staff(request)


urlpatterns = [
    path("casework/staff/", staff),
    path("library-preview/collections/", include("apps.public_collections.routes")),
    *campaign_patterns,
]
