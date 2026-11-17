"""Owned test composition over existing loopback routes; no public activation."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import dispatch

urlpatterns = [
    path("casework/staff/", dispatch, name="casework_staff"),
    *(p for p in campaign_patterns if getattr(p, "name", None) != "casework_staff"),
]
