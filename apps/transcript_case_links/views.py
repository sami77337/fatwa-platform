"""Same staff URL and trusted session; this dispatcher adds only transcript actions."""

from pathlib import Path

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _provider
from apps.fast8_transcript_queue.workbench.services import export_bundle, open_document
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, validate_identity

from . import services

ACTIONS = {
    "transcripts",
    "transcript_open",
    "transcript_preview",
    "transcript_attach",
    "transcript_example",
}


def _page(request, provider, identity, *, selected=None, preview=None, message=""):
    rows = cases.list_cases(
        subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
    )
    links = (
        services.read_links(
            case_id=selected["case_id"],
            subject_id=identity.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        if selected
        else []
    )
    get_token(request)
    return private(
        render(
            request,
            "transcript_case_links/desk.html",
            {
                "cases": rows,
                "selected": selected,
                "preview": preview,
                "links": links,
                "message": message,
            },
        )
    )


@sensitive_post_parameters()
@csrf_protect
def staff(request):
    if request.method != "POST" or request.POST.get("action") not in ACTIONS:
        from apps.requester_team_journey.views import staff as campaign_staff

        return campaign_staff(request)
    try:
        provider = _provider()
        provider_id = provider.provider_id
        actor = current_staff(request, provider)
        provider = RequestDirectory(provider, actor, authenticated_provider_id=provider_id)
        action = request.POST.get("action")
        required = {"action"}
        if action not in {"transcripts", "transcript_example"}:
            required.add("case_ref")
        if action == "transcript_preview":
            required.add("synthetic_only")
            fields = request.POST
            if (
                request.content_type != "multipart/form-data"
                or set(fields) != required | {"csrfmiddlewaretoken"}
                or any(len(fields.getlist(k)) != 1 for k in fields)
                or set(request.FILES) != {"bundle"}
                or len(request.FILES.getlist("bundle")) != 1
                or fields["synthetic_only"] != "yes"
            ):
                raise InvalidForm("invalid_transcript_upload")
        else:
            if action == "transcript_attach":
                required |= {"upload_id", "external_id", "confirm"}
            fields = _form(request, required)
            if request.FILES:
                raise InvalidForm("invalid_transcript_form")
        if action == "transcripts":
            return _page(request, provider, actor)
        if action == "transcript_example":
            raw = (
                Path(__file__).resolve().parents[2]
                / "tools/transcript_pipeline/examples/synthetic-manual.json"
            ).read_bytes()
            data = export_bundle(open_document(raw, ".json", synthetic_fixtures_only=True))
            return private(
                HttpResponse(
                    data,
                    content_type="application/zip",
                    headers={
                        "Content-Disposition": 'attachment; filename="synthetic-reviewed-transcript.zip"',
                    },
                )
            )
        validate_identity(actor, case_key=fields["case_ref"])
        rows = cases.list_cases(
            subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        selected = next((r for r in rows if r["public_ref"] == fields["case_ref"]), None)
        if selected is None:
            return denied("transcript_case_unavailable", 404)
        common = {
            "case_id": selected["case_id"],
            "subject_id": actor.subject_id,
            "provider": provider,
            "synthetic_fixtures_only": True,
        }
        preview = None
        message = ""
        if action == "transcript_preview":
            uploaded = request.FILES["bundle"]
            if uploaded.size > services.MAX_BUNDLE:
                return denied("transcript_bundle_too_large", 413)
            preview = services.preview(**common, bundle=uploaded.read(services.MAX_BUNDLE + 1))
        elif action == "transcript_attach":
            if fields["confirm"] != "yes":
                raise InvalidForm("transcript_confirmation_required")
            result = services.attach(
                **common, upload_id=fields["upload_id"], external_id=fields["external_id"]
            )
            selected = cases.read_case(**common)
            message = (
                "حُفظ السؤال دليلًا إضافيًا وأُلغي أي اعتماد سابق. الجواب المصدري لم يصبح مسودة أو فتوى."
                if result["created"]
                else "هذا السؤال مرتبط بالفعل؛ لم يتكرر الدليل أو إصدار الوقائع."
            )
        return _page(request, provider, actor, selected=selected, preview=preview, message=message)
    except (InvalidForm, SuspiciousOperation):
        return denied("transcript_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return private(
            HttpResponse(
                "لم يُحفظ الربط. أعد فتح القضية ومعاينة الحزمة؛ تحقق من صلاحيتك وحداثة الوقائع، "
                "واكتمال مراجعة التفريغ وعدم وجود استيضاح معلّق. تبقى البيانات السابقة محفوظة.",
                status=409,
                content_type="text/plain; charset=utf-8",
            )
        )
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)
