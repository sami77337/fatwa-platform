"""One local casework surface for requester and scoped Mufti team workflows."""

from django.urls import include, path

from apps.answer_media import views as answer_media
from apps.case_attachments import views as case_attachments
from apps.casework_web import requester_intake
from apps.requester_team_journey.views import requester, staff
from apps.team_workspace.urls import urlpatterns as team_patterns

urlpatterns = [
    path("library-preview/", include("apps.library_preview.routes")),
    path(
        "casework/status/attachments/<uuid:attachment_id>/",
        case_attachments.requester_file,
        name="requester_attachment_file",
    ),
    path(
        "casework/staff/attachments/<uuid:attachment_id>/",
        case_attachments.staff_file,
        name="staff_attachment_file",
    ),
    path(
        "casework/status/answer-media/<uuid:part_id>/",
        answer_media.requester_file,
        name="answer_media_requester_file",
    ),
    path(
        "casework/staff/answer-media/<uuid:part_id>/",
        answer_media.staff_file,
        name="answer_media_staff_file",
    ),
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
