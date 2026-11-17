"""Standalone composition; integrate ACTIONS/workspace in the shared staff dispatcher."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import ACTIONS, workspace


def staff(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    from apps.requester_team_journey.views import staff as campaign_staff

    return campaign_staff(request)


urlpatterns = [path("casework/staff/", staff), *campaign_patterns]
