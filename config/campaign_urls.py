"""One local casework surface for requester and scoped Mufti team workflows."""

from django.urls import path

from apps.casework_web import requester_intake
from apps.requester_access_review.views import requester
from apps.team_workspace.campaign import staff
from apps.team_workspace.urls import urlpatterns as team_patterns

urlpatterns = [
    path("casework/", requester_intake.intake, name="requester_intake"),
    path("casework/status/", requester, name="requester_workspace"),
    # Preserve existing reverse names while resolving to the same private screens.
    path("casework/", requester_intake.intake, name="casework_intake"),
    path("casework/status/", requester, name="casework_status"),
    path("casework/staff/", staff, name="casework_staff"),
    *(
        p
        for p in team_patterns
        if p.name not in {"casework_intake", "casework_status", "casework_staff"}
    ),
]
