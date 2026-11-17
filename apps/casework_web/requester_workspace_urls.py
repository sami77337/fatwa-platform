"""Opt-in requester UI overlay; keep the existing staff and core routes intact."""
from django.urls import path

from . import requester_intake, requester_workspace
from .urls import urlpatterns as existing_patterns

urlpatterns = [
    path("casework/", requester_intake.intake, name="requester_intake"),
    path("casework/status/", requester_workspace.workspace, name="requester_workspace"),
    *existing_patterns,
]
