"""Current-case context, never a remembered case grant or a second operational store."""

import re

from django.apps import apps
from django.conf import settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.views import _provider
from apps.team_workspace import presentation

from .workflow import describe_work

REFERENCE = re.compile(r"FT-[0-9]{4}-[A-F0-9]{20}")

TABS = (
    ("overview", "case_workspace", "القضية والمراجعة", None),
    ("origins", "source_timeline", "أصل الأحداث وتسلسلها", "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED"),
    ("attachments", "attachment_list", "مرفقات الوقائع", "FATWA_CASE_ATTACHMENTS_ENABLED"),
    ("rights", "rights_desk", "حقوق المصادر ومراجعتها", "FATWA_SOURCE_RIGHTS_ENABLED"),
    ("citations", "citations", "الإحالات العلمية", "FATWA_CASE_CITATIONS_ENABLED"),
    ("answer", "answer_media", "أجزاء الجواب والإتاحة", "FATWA_ANSWER_MEDIA_ENABLED"),
    ("delivery", "composite_open", "التوصيل المركب", "FATWA_COMPOSITE_DELIVERY_ENABLED"),
    ("publication", "pub_open", "نسخة النشر المستقلة", "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED"),
)


def _active(action):
    if action.startswith("rights_"):
        return "rights"
    if action.startswith("source_"):
        return "origins"
    if action.startswith("attachment_"):
        return "attachments"
    if action.startswith("citation"):
        return "citations"
    if action.startswith("answer_"):
        return "answer"
    if action.startswith("composite_") or action in {"prepare", "stage", "quarantine", "export"}:
        return "delivery"
    if action.startswith("pub_"):
        return "publication"
    return "overview"


def _metadata(common, snapshot):
    """Select metadata only, under the canonical case/identity/integrity boundary."""
    with cases._staff_case(common["case_id"], common["subject_id"], common["provider"], True) as (
        case,
        _,
    ):
        if (case.revision, case.evidence_version) != (
            snapshot["revision"],
            snapshot["evidence_version"],
        ):
            raise cases.CaseConflict("mufti_workspace_case_changed")
        attachments = []
        if getattr(settings, "FATWA_CASE_ATTACHMENTS_ENABLED", False) is True and apps.is_installed(
            "apps.case_attachments"
        ):
            from apps.case_attachments.models import CaseAttachment

            for row in (
                CaseAttachment.objects.filter(case=case)
                .order_by("evidence__version")
                .values(
                    "id",
                    "filename",
                    "media_type",
                    "kind",
                    "size",
                    "sha256",
                    "source",
                    "created_at",
                    "evidence__version",
                )
            ):
                attachments.append(
                    {
                        "id": str(row["id"]),
                        "filename": row["filename"],
                        "media_type": row["media_type"],
                        "kind": row["kind"],
                        "size": row["size"],
                        "sha256": row["sha256"],
                        "source": row["source"],
                        "created_at": row["created_at"],
                        "evidence_version": row["evidence__version"],
                        "preview_url": f"/casework/staff/attachments/{row['id']}/",
                    }
                )
        manifest = None
        if snapshot["latest_answer"] and apps.is_installed("apps.answer_media"):
            from apps.answer_media.models import AnswerManifest

            manifest = (
                AnswerManifest.objects.filter(answer_id=snapshot["latest_answer"]["id"])
                .values("sha256", "part_count")
                .first()
            )
        release = {
            "recorded": False,
            "enabled": getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", False) is True
            and getattr(settings, "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED", False) is True,
        }
        if manifest and case.approved_answer_id and snapshot["status"] == "ANSWERED":
            from apps.answer_media.models import PrivateAnswerRelease

            release["recorded"] = PrivateAnswerRelease.objects.filter(
                manifest_id=case.approved_answer_id,
                decision__answer_id=case.approved_answer_id,
                decision__case=case,
                decision__action="APPROVE",
                decision__evidence_version=case.evidence_version,
                evidence_version=case.evidence_version,
                manifest_sha256=manifest["sha256"],
            ).exists()
        return_reason = ""
        if snapshot["status"] == "RETURNED_FOR_CHANGES" and snapshot["latest_answer"]:
            return_reason = (
                case.decisions.filter(
                    answer_id=snapshot["latest_answer"]["id"], action="RETURN_FOR_CHANGES"
                )
                .values_list("note", flat=True)
                .first()
                or ""
            )
        # A provider revocation during metadata projection must invalidate the entire frame.
        cases._identity(common["provider"], common["subject_id"], case)
        return attachments, manifest, release, return_reason


def case_workspace(request):
    """Enabled, authenticated POST case selections only; eligible failures propagate.

    The containing native handler catches IdentityUnavailable/CaseConflict. Returning
    an empty context after revocation would leave its earlier private content visible.
    Original bytes, media parsers and delivery verifiers are deliberately not invoked.
    """
    if (
        getattr(settings, "FATWA_MUFTI_WORKSPACE_ENABLED", False) is not True
        or getattr(request, "_mufti_workspace_error", False) is True
        or request.path != "/casework/staff/"
        or request.method != "POST"
        or (
            "case_ref" not in request.POST
            and not getattr(request, "publication_authorized_case_ref", None)
        )
    ):
        return {}
    references = request.POST.getlist("case_ref")
    resolved = getattr(request, "publication_authorized_case_ref", None)
    # The native publication view sets this only after canonical desk authorization.
    # It is never a browser field or a replacement for the fresh scope check below.
    if not references and request.POST.get("action") == "pub_open" and resolved:
        references = [resolved]
    elif resolved and references != [resolved]:
        raise cases.CaseConflict("mufti_workspace_selection_invalid")
    if len(references) != 1 or REFERENCE.fullmatch(references[0]) is None:
        raise cases.CaseConflict("mufti_workspace_selection_invalid")
    if len(request.POST.getlist("action")) != 1:
        raise cases.CaseConflict("mufti_workspace_selection_invalid")
    directory = _provider()
    provider_id = directory.provider_id
    identity = current_staff(request, directory, case_key=references[0])
    provider = RequestDirectory(directory, identity, authenticated_provider_id=provider_id)
    case_id = Case.objects.filter(public_ref=references[0]).values_list("pk", flat=True).first()
    if case_id is None:
        raise cases.CaseConflict("case_access_denied")
    common = {
        "case_id": str(case_id),
        "subject_id": identity.subject_id,
        "provider": provider,
        "synthetic_fixtures_only": True,
    }
    snapshot = presentation.read_workspace_case(**common, include_answer_manifest=False)
    origins = []
    if getattr(settings, "FATWA_SOURCE_CASE_INTAKE_ENABLED", False) is True and apps.is_installed(
        "apps.source_case_intake"
    ):
        from apps.source_case_intake.services import staff_origins

        origins = staff_origins(**common)
    attachments, manifest, release, return_reason = _metadata(common, snapshot)
    # Check the live browser identity after all reads as well as at entry.
    current_staff(request, directory, case_key=references[0])
    active = _active(request.POST["action"])
    tabs = [
        {"key": key, "action": action, "label": label, "active": key == active}
        for key, action, label, flag in TABS
        if flag is None or getattr(settings, flag, False) is True
    ]
    latest = snapshot["latest_answer"]
    original_origin = next((row for row in origins if row["evidence_version"] == 1), None)
    source = original_origin["source"] if original_origin else snapshot["source_channel"]
    return {
        "mufti_workspace": {
            "case": snapshot,
            "origins": origins,
            "attachments": attachments,
            "manifest": manifest,
            "tabs": tabs,
            "active": active,
            "answer_revision": latest["revision"] if latest else 0,
            "approved": snapshot["status"] == "ANSWERED" and bool(snapshot["approved_answer_id"]),
            "source_label": {
                "WEBSITE": "الموقع",
                "TELEGRAM": "Telegram",
                "WHATSAPP": "WhatsApp",
                "YOUTUBE": "YouTube",
            }.get(source, source),
            "source_label_is_origin": original_origin is not None,
            "private_status": "تُراجع الإتاحة الخاصة في لوحة أجزاء الجواب؛ الاعتماد وحده لا يتيح الملفات.",
            "delivery_status": "افتح لوحة التوصيل للتحقق من الخطة وإثبات كل جزء؛ هذه اللوحة لا تثبت التسليم أو القراءة.",
            "verification_checked": False,
            "workflow": describe_work(
                snapshot, manifest=manifest, release=release, return_reason=return_reason, tabs=tabs
            ),
        }
    }
