"""Isolated composition using the real staff authentication and native endpoint."""

from django.urls import path

from apps.requester_team_journey.views import staff as existing_staff
from config.campaign_urls import urlpatterns as campaign_patterns

from .views import ACTIONS, entry, workspace


def staff(request):
    if request.method in {"GET", "HEAD"}:
        return entry(request)
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    return existing_staff(request)


urlpatterns = [path("casework/staff/", staff), *campaign_patterns]
