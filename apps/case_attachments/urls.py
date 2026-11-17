"""Isolated test URL composition; integration uses the same existing guarded paths."""

from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from . import views

urlpatterns = [
    path("casework/status/attachments/<uuid:attachment_id>/", views.requester_file),
    path("casework/staff/attachments/<uuid:attachment_id>/", views.staff_file),
    path("casework/status/", views.requester, name="attachment_requester"),
    path("casework/staff/", views.staff, name="attachment_staff"),
    *campaign_patterns,
]
