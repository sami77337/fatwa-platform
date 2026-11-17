"""Compose optional access review with the team screen under the existing guard."""

from apps.requester_access_review import views as access_views

from .views import workspace


def staff(request):
    if request.method == "POST" and request.POST.get("action") in {
        "access_queue",
        "access_acknowledge",
        "access_close",
    }:
        return access_views.staff(request)
    request.campaign_access_review = True
    return workspace(request)
