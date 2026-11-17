from django.urls import path

from config.campaign_urls import urlpatterns as campaign_patterns

from . import views

urlpatterns = [
    path("casework/staff/", views.dispatch_staff),
    path("casework/status/", views.dispatch_requester),
    path(
        "casework/staff/answer-media/<uuid:part_id>/",
        views.staff_file,
        name="answer_media_staff_file",
    ),
    path(
        "casework/status/answer-media/<uuid:part_id>/",
        views.requester_file,
        name="answer_media_requester_file",
    ),
    *campaign_patterns,
]
