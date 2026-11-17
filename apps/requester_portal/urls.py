"""Overlay existing allowed status URL; keep original guarded media endpoints."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import portal

urlpatterns = [
    path("casework/status/", portal, name="requester_portal"),
    *campaign_patterns,
]
