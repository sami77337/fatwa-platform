"""Isolated integration profile; production and shared routing remain untouched."""

from django.urls import path

from apps.requester_team_journey.views import staff
from config.campaign_urls import urlpatterns as campaign_patterns

from .views import ACTIONS, desk


def citation_staff(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return desk(request)
    return staff(request)


urlpatterns = [path("casework/staff/", citation_staff), *campaign_patterns]
