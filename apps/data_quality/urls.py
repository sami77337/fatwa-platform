from django.urls import path

from apps.casework_web import views as core
from apps.requester_team_journey import views as journey
from config.campaign_urls import urlpatterns as campaign

from . import views


def staff(request):
    return (
        views.workspace(request)
        if request.POST.get("action") in views.ACTIONS
        else journey.staff(request)
    )


urlpatterns = [
    path("casework/staff/quality/", views.index),
    path("casework/staff/", staff),
    path("casework/staff/login/", core.staff_login),
    *campaign,
]
