"""Owned test overlay; shared dispatcher wiring remains with integration."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import dispatch

urlpatterns = [
    path("casework/staff/", dispatch, name="casework_staff"),
    *(p for p in campaign_patterns if getattr(p, "name", None) != "casework_staff"),
]
