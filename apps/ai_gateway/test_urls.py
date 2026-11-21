"""Isolated URL composition; shared campaign wiring belongs to the integrator."""

from django.urls import include, path

urlpatterns = [
    path("casework/ai-citations/", include("apps.ai_gateway.urls")),
    path("", include("config.campaign_urls")),
]
