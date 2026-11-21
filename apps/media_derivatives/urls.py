"""Finite native media routes included by the actual campaign composition."""

from django.urls import path

from . import views

urlpatterns = [
    path("casework/staff/media-jobs/", views.workspace, name="media-derivative-workspace"),
    path(
        "casework/staff/media-jobs/<uuid:job_id>/output/",
        views.output,
        name="media-derivative-output",
    ),
]
