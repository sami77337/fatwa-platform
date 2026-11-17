"""Owned test composition; coordinator dispatches ACTIONS from the shared desk."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from .views import dispatch, styles

urlpatterns = [
    path("research-workspace.css", styles, name="research_workspace_css"),
    path("casework/staff/", dispatch, name="casework_staff"),
    *(p for p in campaign_patterns if getattr(p, "name", None) != "casework_staff"),
]
