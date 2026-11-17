"""Native case research navigation with browser-bound, rights-rechecked source links."""

from dataclasses import asdict

from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.delivery_queue import services as queue
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services
from .rights import Resource

ACTIONS = {
    "research_open",
    "research_search",
    "research_view",
    "research_back",
    "research_add",
    "research_file",
}
SALT = "research-workspace.v11"
FILTERS = {"query", "kind", "edition_id", "printed_part", "printed_page"}


def _bind(request, identity, provider, case_ref):
    return browser_proof(
        request,
        SALT,
        "|".join(
            [
                provider.provider_id,
                identity.subject_id,
                identity.auth_epoch,
                case_ref,
            ]
        ),
    )


def _token(binding, result, filters, resource=None):
    return signing.dumps(
        {
            "binding": binding,
            "revision": result["revision"],
            "evidence_version": result["evidence_version"],
            "filters": filters,
            "resource": resource,
        },
        salt=SALT,
        compress=True,
    )


def _load(raw, binding):
    if type(raw) is not str or not 1 <= len(raw) <= 8000:
        raise InvalidForm("research_state_invalid")
    try:
        data = signing.loads(raw, salt=SALT, max_age=1800)
        if (
            set(data) != {"binding", "revision", "evidence_version", "filters", "resource"}
            or data["binding"] != binding
        ):
            raise ValueError()
        cases._mutation_versions(data["revision"], data["evidence_version"])
        if set(data["filters"]) != FILTERS:
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError, signing.BadSignature) as exc:
        raise InvalidForm("research_state_invalid") from exc


def _page(request, *, code=200, **context):
    get_token(request)
    return private(render(request, "research_workspace/desk.html", context, status=code))


@sensitive_post_parameters("state", "note")
@csrf_protect
def workspace(request):
    try:
        services._enabled()
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS:
            raise InvalidForm("research_form_invalid")
        required = {"action", "case_ref"}
        if action == "research_search":
            required |= FILTERS
        elif action != "research_open":
            required.add("state")
        if action == "research_add":
            required |= {"note", "confirm"}
        fields = _form(request, required)
        if request.FILES:
            raise InvalidForm("research_upload_unexpected")
        directory = _provider()
        identity = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        common = dict(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        selected = next(
            (c for c in cases.list_cases(**common) if c["public_ref"] == fields["case_ref"]), None
        )
        if selected is None:
            return _page(request, code=404, error="القضية أو المصدر غير متاح.")
        common["case_id"] = selected["case_id"]
        binding = _bind(request, identity, provider, fields["case_ref"])
        filters = dict(query="", kind="all", edition_id=None, printed_part="", printed_page=None)
        opened, notice, selected_resource = None, "", None
        if action == "research_search":
            filters = {key: fields[key] for key in FILTERS}
            for key in ("edition_id", "printed_page"):
                filters[key] = _integer(filters[key]) if filters[key] else None
        elif action != "research_open":
            state = _load(fields["state"], binding)
            filters = state["filters"]
            with (
                queue.synthetic_queue_atomic(),
                cases._staff_case(
                    selected["case_id"],
                    identity.subject_id,
                    provider,
                    True,
                    expected_revision=state["revision"],
                    expected_evidence_version=state["evidence_version"],
                ),
            ):
                if action != "research_back":
                    selected_resource = Resource(**state["resource"])
                if action == "research_add":
                    if fields["confirm"] != "yes":
                        raise InvalidForm("research_confirmation_required")
                    services.add_citation(
                        **common,
                        resource=selected_resource,
                        note=fields["note"],
                        expected_revision=state["revision"],
                        expected_evidence_version=state["evidence_version"],
                    )
                    notice = "أُضيفت الإحالة الدقيقة إلى إصدار جديد من الجواب المحفوظ مع الحفاظ على وسائطه. يلزم اعتماد بشري جديد."
                elif action in {"research_view", "research_file"}:
                    if action == "research_file":
                        opened = services.open_resource(**common, resource=selected_resource)
                        if selected_resource.kind not in {"ATTACHMENT", "ANSWER_MEDIA"}:
                            raise InvalidForm("research_media_required")
                        response = HttpResponse(opened["raw"], content_type=opened["media_type"])
                        # Existing media validators restrict filename characters.
                        response["Content-Disposition"] = (
                            f'attachment; filename="{opened["filename"]}"'
                        )
                        return private(response)
                    if selected_resource.kind in {"ATTACHMENT", "ANSWER_MEDIA"}:
                        raise InvalidForm("research_media_action_required")
        result = services.search(**common, **filters)
        if action == "research_view":
            # Recheck the browser's original case version and exact source rights
            # after search as well: never render a previously read, now-revoked text.
            with (
                queue.synthetic_queue_atomic(),
                cases._staff_case(
                    selected["case_id"],
                    identity.subject_id,
                    provider,
                    True,
                    expected_revision=state["revision"],
                    expected_evidence_version=state["evidence_version"],
                ),
            ):
                opened = services.open_resource(**common, resource=selected_resource)
        for row in result["results"]:
            row["state"] = _token(binding, result, filters, row["resource"])
        return _page(
            request,
            result=result,
            filters=filters,
            notice=notice,
            opened=opened,
            opened_kind=selected_resource.kind if selected_resource else None,
            selection=_token(binding, result, filters, asdict(selected_resource))
            if selected_resource
            else "",
            back_state=_token(binding, result, filters),
        )
    except IdentityUnavailable:
        return _page(request, code=403, error="يلزم دخول المفتي المخوّل ونطاق القضية الحالي.")
    except (InvalidForm, SuspiciousOperation, TypeError):
        return _page(
            request, code=400, error="النموذج أو سياق العودة غير صالح. أعد فتح البحث من القضية."
        )
    except (cases.CaseConflict, queue.QueueConflict, ValueError):
        return _page(
            request,
            code=409,
            error="تعذر التحقق من المصدر أو حق استخدامه أو الإصدار الحالي. أعد فتح البحث؛ لا تُستبدل إحالة بالتخمين.",
        )
    except (DatabaseError, SyntheticWriteDenied):
        return _page(request, code=503, error="تعذر الوصول إلى المصادر المعتمدة الآن.")


@csrf_protect
def landing(request):
    """Standalone owned composition; integration embeds entry.html in the case desk."""
    try:
        services._enabled()
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        rows = cases.list_cases(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        return private(render(request, "research_workspace/landing.html", {"cases": rows}))
    except IdentityUnavailable:
        return _page(request, code=403, error="يلزم دخول المفتي المخوّل.")
    except (cases.CaseConflict, SyntheticWriteDenied, DatabaseError):
        return _page(request, code=503, error="البحث غير متاح الآن.")


def styles(request):
    return private(
        HttpResponse(
            "select{font:inherit;max-width:100%;width:100%;padding:.5rem}select:focus{outline:3px solid #9c6800;outline-offset:3px}",
            content_type="text/css",
        )
    )


def dispatch(request):
    if request.method == "GET":
        return landing(request)
    if request.method == "POST" and request.POST.get("action") in ACTIONS:
        return workspace(request)
    from apps.requester_team_journey.views import staff

    return staff(request)
