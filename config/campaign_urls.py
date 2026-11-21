"""One local casework surface for requester and scoped Mufti team workflows."""

from django.urls import include, path

from apps.answer_media import related_views as answer_related
from apps.answer_media import views as answer_media
from apps.case_attachments import views as case_attachments
from apps.casework_web import requester_intake
from apps.data_quality import views as data_quality
from apps.pdf_citations import views as pdf_citations
from apps.requester_team_journey.views import requester, staff
from apps.research_library import editor as library_editor
from apps.research_workspace.views import styles as research_styles
from apps.team_workspace.urls import urlpatterns as team_patterns
from apps.timed_citations import views as timed_citations


def privacy_workspace(request):
    # Keep the optional editor lazy while its explicit feature remains closed.
    from django.conf import settings

    from apps.casework_web.guard import denied

    if getattr(settings, "FATWA_DATA_PRIVACY_ENABLED", False) is not True:
        return denied("privacy_management_unavailable", 404)
    from apps.data_privacy.views import workspace

    return workspace(request)


urlpatterns = [
    path("casework/staff/privacy/", privacy_workspace),
    path("casework/operations/privacy/", privacy_workspace),
    path("casework/sessions/", include("apps.staff_sessions.urls")),
    path("casework/operations/sessions/", include("apps.staff_sessions.urls")),
    path("", include("apps.operational_workspace.urls")),
    path("", include("apps.public_reader_tools.urls")),
    path("", include("apps.staff_shell.urls")),
    path("casework/staff/answer-media/related.mjs", answer_related.script, name="answer_related_script"),
    path("", include("apps.public_teaching.urls")),
    path("casework/precise-citations/", include("apps.precise_citations.urls")),
    path("casework/ai-citations/", include("apps.ai_gateway.urls")),
    path("", include("apps.public_answer_media.urls")),
    path("casework/staff/library/<uuid:version_id>/file/", library_editor.file, name="library_staff_file"),
    path("casework/staff/library/<uuid:version_id>/download/", library_editor.file, {"download": True}, name="library_staff_download"),
    path("casework/staff/quality/", data_quality.index, name="data_quality"),
    path("casework/staff/pdf-citations/<uuid:citation_id>/document/", pdf_citations.document, name="pdf_document"),
    path("casework/staff/pdf-citations/<uuid:citation_id>/review-document/", pdf_citations.review_document, name="pdf_review_document"),
    path("casework/staff/pdf-citations/<uuid:citation_id>/page/", pdf_citations.selected_page, name="pdf_selected_page"),
    path("casework/staff/pdf-citations/<uuid:citation_id>/review-page/", pdf_citations.review_selected_page, name="pdf_review_selected_page"),
    path("", include("apps.browser_audio.assets")),
    path("casework/staff/timed-citations/<uuid:citation_id>/audio/", timed_citations.audio, name="timed_audio"),
    path("casework/staff/timed-citations/<uuid:citation_id>/review-audio/", timed_citations.review_audio, name="timed_review_audio"),
    path("research-workspace.css", research_styles, name="research_styles"),
    path("library-preview/api/v1/materials/", include("apps.material_api.urls")),
    path("library-preview/materials/", include("apps.research_library.routes")),
    path("library-preview/collections/", include("apps.public_collections.routes")),
    path("library-preview/knowledge/", include("apps.public_knowledge.routes")),
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
