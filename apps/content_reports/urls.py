"""Isolated composition used to verify the actual existing HTTP endpoint."""

from django.urls import path

from apps.requester_portal.urls import urlpatterns as portal_patterns
from apps.requester_team_journey.views import staff as existing_staff

from .views import ACTIONS, workspace


def staff(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    return existing_staff(request)


urlpatterns = [path("casework/staff/", staff), *portal_patterns]
