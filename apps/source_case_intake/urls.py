"""App-local composition; integrator dispatches ACTIONS from the common staff view."""

from django.urls import path

from apps.requester_team_journey.views import staff
from config.campaign_urls import urlpatterns as campaign_patterns

from .views import ACTIONS, desk


def source_staff(request):
    if request.method in {"GET", "HEAD"} or request.POST.get("action") in ACTIONS:
        return desk(request)
    return staff(request)


urlpatterns = [path("casework/staff/", source_staff), *campaign_patterns]
