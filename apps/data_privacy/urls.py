"""Test composition; coordinator wires these same exact routes into campaign URLs."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import workspace

urlpatterns = [
    path("casework/staff/privacy/", workspace, name="privacy-classifications"),
    path("casework/operations/privacy/", workspace, name="operational-privacy-classifications"),
    *campaign_patterns,
]
