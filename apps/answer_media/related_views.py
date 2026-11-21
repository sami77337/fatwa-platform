"""Read-only source side panel; it never receives or saves the answer draft."""

from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.canonical_search import policy
from apps.canonical_search import services as search
from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity

from .editor_boundary import EditorBoundary

ACTIONS = frozenset(
    {"answer_media_related_search", "answer_media_related_open", "answer_media_related_back"}
)
SALT = "fatwa.answer-related.native.v1"
COMMON = {
    "binding",
    "intent",
    "editor_case_id",
    "case_ref",
    "revision",
    "evidence_version",
    "query",
    "mode",
    "scope",
}


def _enabled():
    if (
        getattr(settings, "FATWA_ANSWER_RELATED_ENABLED", False) is not True
        or getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("answer_related_disabled")


def _binding(request, base, case_ref):
    actor = resolve_identity(base["provider"], base["subject_id"], case_key=case_ref)
    return browser_proof(
        request,
        SALT,
        "|".join((base["provider"].provider_id, actor.subject_id, actor.auth_epoch, case_ref)),
    )


def _token(request, base, values, intent, **extra):
    return signing.dumps(
        {
            **values,
            **extra,
            "intent": intent,
            "binding": _binding(request, base, values["case_ref"]),
        },
        salt=SALT,
        compress=True,
    )


def seed(request, base, selected):
    if getattr(settings, "FATWA_ANSWER_RELATED_ENABLED", False) is not True:
        return None
    values = dict(
        editor_case_id=str(base["case_id"]),
        case_ref=selected["public_ref"],
        revision=selected["revision"],
        evidence_version=selected["evidence_version"],
        query="",
        mode="FTS",
        scope="CASE",
    )
    return {
        "values": values,
        "state": _token(request, base, values, "SEARCH"),
        "result": None,
        "opened": None,
    }


def script(request):
    try:
        _enabled()
        if request.method not in {"GET", "HEAD"} or request.GET:
            return denied("answer_related_script_unavailable", 404)
        return private(
            HttpResponse(
                (Path(__file__).parent / "related.mjs").read_text(),
                content_type="text/javascript; charset=utf-8",
            ),
            head=request.method == "HEAD",
        )
    except cases.CaseConflict:
        return denied("answer_related_disabled", 404)


@sensitive_post_parameters("query", "state")
@csrf_protect
def workspace(request):
    try:
        _enabled()
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS:
            raise InvalidForm("answer_related_form_invalid")
        fields = {"action", "case_ref", "state", "csrfmiddlewaretoken"}
        if action == "answer_media_related_search":
            fields |= {"query", "mode", "scope"}
        if (
            request.content_type != "application/x-www-form-urlencoded"
            or set(request.POST) != fields
            or request.GET
            or request.FILES
            or any(len(request.POST.getlist(key)) != 1 for key in fields)
        ):
            raise InvalidForm("answer_related_form_invalid")
        directory = _provider()
        actor = current_staff(request, directory, case_key=request.POST["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        case = Case.objects.filter(public_ref=request.POST["case_ref"]).first()
        if case is None:
            raise cases.CaseConflict("answer_related_case_unavailable")
        base = dict(
            case_id=str(case.pk),
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        state = signing.loads(request.POST["state"], salt=SALT, max_age=900)
        intent = action.rsplit("_", 1)[1].upper()
        expected = COMMON | (
            {"source_case_id", "generation_id", "document_id"} if intent == "OPEN" else set()
        )
        if (
            type(state) is not dict
            or set(state) != expected
            or state["intent"] != intent
            or state["editor_case_id"] != str(case.pk)
            or state["case_ref"] != case.public_ref
            or state["binding"] != _binding(request, base, case.public_ref)
        ):
            raise InvalidForm("answer_related_selection_invalid")
        values = {key: state[key] for key in COMMON - {"intent", "binding"}}
        if intent == "SEARCH":
            values.update(
                query=request.POST["query"], mode=request.POST["mode"], scope=request.POST["scope"]
            )
        with synthetic_queue_atomic():
            editor = EditorBoundary(provider)
            # The search boundary locks the whole selected scope in PK order.
            # Do not lock the editor case separately before a multi-case read.
            with policy.boundary(
                **base, action="OPEN" if intent == "OPEN" else "SEARCH", scope=values["scope"]
            ) as context:
                active = context.cases[str(case.pk)]
                cases._versions(active, values["revision"], values["evidence_version"])
                opened, result = None, None
                if intent == "OPEN":
                    if state["source_case_id"] not in context.cases:
                        raise cases.CaseConflict("answer_related_source_unavailable")
                    opened = search.open_in_context(
                        context,
                        case_id=state["source_case_id"],
                        generation_id=state["generation_id"],
                        document_id=state["document_id"],
                    )
                else:
                    result = search.search_in_context(
                        context, value=values["query"], mode=values["mode"]
                    )
                    for row in result["results"]:
                        row["state"] = _token(
                            request,
                            base,
                            values,
                            "OPEN",
                            source_case_id=row["case_id"],
                            generation_id=row["generation_id"],
                            document_id=row["document_id"],
                        )
                panel = {
                    "values": values,
                    "state": _token(request, base, values, "SEARCH"),
                    "back": _token(request, base, values, "BACK"),
                    "result": result,
                    "opened": opened,
                }
                response = private(render(request, "answer_media/related.html", {"related": panel}))
                response["X-Answer-Related-Panel"] = "1"
            editor.check(actor)
        return response
    except (InvalidForm, SuspiciousOperation, signing.BadSignature, KeyError, TypeError):
        return denied("answer_related_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("answer_related_unavailable_or_stale", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("answer_related_store_unavailable", 503)
