"""Isolated native composition; shared routing remains integrator-owned."""

from django.urls import include, path

from config.campaign_urls import urlpatterns as campaign_patterns

from . import editor


def staff(request):
    if request.method == "POST" and request.POST.get("action") in editor.ACTIONS:
        return editor.workspace(request)
    from apps.requester_team_journey.views import staff as campaign_staff

    return campaign_staff(request)


urlpatterns = [
    path("casework/staff/", staff),
    path("library-preview/knowledge/", include("apps.public_knowledge.routes")),
    *campaign_patterns,
]
