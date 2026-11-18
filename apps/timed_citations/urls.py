"""Test-only composition; integrator installs actions and guarded GET explicitly."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import ACTIONS, audio, review_audio, workspace


def staff(request):
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    from apps.requester_team_journey.views import staff as existing

    return existing(request)


urlpatterns = [
    path("casework/staff/", staff),
    path("casework/staff/timed-citations/<uuid:citation_id>/audio/", audio, name="timed_audio"),
    path(
        "casework/staff/timed-citations/<uuid:citation_id>/review-audio/",
        review_audio,
        name="timed_review_audio",
    ),
    *campaign_patterns,
]
