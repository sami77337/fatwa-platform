"""Integration seam: replace only the existing staff screen, preserving its URL."""

from django.urls import path

from apps.casework_web.urls import urlpatterns as casework_patterns

from .views import stylesheet, workspace

urlpatterns = [
    path("casework/staff/", workspace, name="casework_staff"),
    path("casework/casework.css", stylesheet, name="casework_css"),
    *(pattern for pattern in casework_patterns
      if pattern.name not in {"casework_staff", "casework_css"}),
]
