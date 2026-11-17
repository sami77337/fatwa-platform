"""Standalone test composition; integrators include library_preview.routes instead."""

from django.urls import include, path

from config.campaign_urls import urlpatterns as campaign_patterns

urlpatterns = [
    path("library-preview/", include("apps.library_preview.routes")),
    *campaign_patterns,
]
