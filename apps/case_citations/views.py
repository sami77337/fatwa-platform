"""Citation forms share the authenticated, CSRF-bound team workspace URL."""

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, validate_identity

from . import services

ACTIONS = {"citations", "citation_search", "citation_select", "citation_save", "citation_source"}


@sensitive_post_parameters("text", "editorial_note")
@csrf_protect
def desk(request):
    try:
        provider = _provider()
        provider_id = provider.provider_id
        actor = current_staff(request, provider)
        provider = RequestDirectory(provider, actor, authenticated_provider_id=provider_id)
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS:
            raise InvalidForm("citation_action_invalid")
        required = {"action", "case_ref"}
        if action == "citation_search":
            required |= {"query", "edition_id"}
        elif action in {"citation_select", "citation_source"}:
            required |= {"edition_id", "source_row_id"}
        elif action == "citation_save":
            required |= {
                "edition_id",
                "source_row_id",
                "source_sha256",
                "editorial_note",
                "text",
                "revision",
                "evidence_version",
                "confirm",
            }
        fields = _form(request, required)
        if request.FILES:
            raise InvalidForm("citation_files_not_supported")
        validate_identity(actor, case_key=fields["case_ref"])
        rows = cases.list_cases(
            subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        selected = next((r for r in rows if r["public_ref"] == fields["case_ref"]), None)
        if selected is None:
            return denied("citation_case_unavailable", 404)
        common = dict(
            case_id=selected["case_id"],
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        source, message = None, ""
        if action == "citation_save":
            if fields["confirm"] != "yes":
                raise InvalidForm("human_citation_review_required")
            selected = services.save_cited_answer(
                **common,
                text=fields["text"],
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
                selections=[
                    dict(
                        edition_id=_integer(fields["edition_id"]),
                        source_row_id=_integer(fields["source_row_id"]),
                        source_sha256=fields["source_sha256"],
                        editorial_note=fields["editorial_note"],
                    )
                ],
            )
            message = "حُفظ إصدار جواب جديد بإحالته. أُلغي الاعتماد السابق وتلزم مراجعة المفتي."
        elif action in {"citation_select", "citation_source"}:
            source = services.read_source(
                **common,
                edition_id=_integer(fields["edition_id"]),
                source_row_id=_integer(fields["source_row_id"]),
            )
        found = services.search_sources(
            **common,
            query=fields.get("query", ""),
            edition_id=_integer(fields["edition_id"]) if action == "citation_search" else None,
        )
        links = services.read_citations(**common)
        get_token(request)
        return private(
            render(
                request,
                "case_citations/desk.html",
                {
                    "selected": selected,
                    "source": source,
                    "sources": found,
                    "links": links,
                    "message": message,
                    "query": fields.get("query", ""),
                    "editing": action == "citation_select",
                    "draft_text": selected["answers"][-1]["text"] if selected["answers"] else "",
                },
            )
        )
    except (InvalidForm, SuspiciousOperation):
        return denied("citation_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("citation_unavailable_or_changed", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("casework_store_unavailable", 503)
