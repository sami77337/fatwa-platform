"""Authorized native forms on the existing guarded staff endpoint."""

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import registry, services

FIELDS = {
    "rights_desk": {"query", "edition_id"},
    "rights_inspect": {"source_id", "revision_number", "query", "edition_id"},
    "rights_register": {"kind", "target_id"},
    "rights_propose": {"source_id", "expected_number", "basis", "note", "ttl_minutes", "uses"},
    "rights_review": {"revision_id", "decision", "confirm", "note"},
    "rights_citation_correct": {"citation_id", "target_id", "note", "revision", "evidence_version"},
    "rights_relation_propose": {"publication_id", "kind", "target_id", "replaces_id", "note"},
    "rights_relation_action": {"publication_id", "relation_id", "decision", "confirm"},
}
ACTIONS = set(FIELDS)


def _fields(request, action):
    allowed = {"action", "case_ref", "csrfmiddlewaretoken"} | FIELDS[action]
    required = allowed - {"csrfmiddlewaretoken", "uses"}
    if request.FILES or set(request.POST) - allowed or required - set(request.POST):
        raise InvalidForm("rights_form_invalid")
    if any(len(values) != 1 for key, values in request.POST.lists() if key != "uses"):
        raise InvalidForm("rights_form_invalid")
    if len(request.POST.getlist("uses")) > 4:
        raise InvalidForm("rights_form_invalid")
    return {key: request.POST.get(key, "") for key in allowed}


@sensitive_post_parameters("basis", "note", "query")
@csrf_protect
def workspace(request):
    try:
        services._enabled()
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS:
            raise InvalidForm("rights_form_invalid")
        fields = _fields(request, action)
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        common = dict(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        selected = next(
            (r for r in cases.list_cases(**common) if r["public_ref"] == fields["case_ref"]), None
        )
        if selected is None:
            return denied("source_rights_unavailable", 404)
        common["case_id"] = selected["case_id"]
        get_token(request)
        if action == "rights_inspect":
            query = fields["query"]
            if len(query) > 100:
                raise InvalidForm("rights_form_invalid")
            cases._text(query, optional=True)
            edition_id = _integer(fields["edition_id"]) if fields["edition_id"] else None
            number = 0 if fields["revision_number"] == "0" else _integer(fields["revision_number"])
            projection = registry.inspect_source(
                **common, source_id=fields["source_id"], revision_number=number
            )
            projection.update(query=query, edition_id=edition_id)
            return private(render(request, "source_rights/inspect.html", projection))
        if action == "rights_register":
            target = (
                _integer(fields["target_id"])
                if fields["kind"] == "TOC_METADATA"
                else fields["target_id"]
            )
            services.register(**common, kind=fields["kind"], target_id=target)
        elif action == "rights_propose":
            if fields["expected_number"] == "0":
                number = 0
            else:
                number = _integer(fields["expected_number"])
            services.propose(
                **common,
                source_id=fields["source_id"],
                expected_number=number,
                uses=request.POST.getlist("uses"),
                basis=fields["basis"],
                note=fields["note"],
                ttl_minutes=_integer(fields["ttl_minutes"]),
            )
        elif action == "rights_review":
            services.review(
                **common,
                revision_id=fields["revision_id"],
                action=fields["decision"],
                confirmed=fields["confirm"] == "yes",
                note=fields["note"],
            )
        elif action == "rights_citation_correct":
            services.correct_citation(
                **common,
                citation_id=fields["citation_id"],
                target_id=_integer(fields["target_id"]),
                note=fields["note"],
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
            )
        elif action == "rights_relation_propose":
            target = (
                _integer(fields["target_id"])
                if fields["kind"] == "REFERENCE"
                else fields["target_id"]
            )
            services.propose_relation(
                **common,
                publication_id=fields["publication_id"],
                kind=fields["kind"],
                target_id=target,
                reason=fields["note"],
                replaces_id=fields["replaces_id"] or None,
            )
        elif action == "rights_relation_action":
            services.act_on_relation(
                **common,
                publication_id=fields["publication_id"],
                relation_id=fields["relation_id"],
                action=fields["decision"],
                confirmed=fields["confirm"] == "yes",
            )
        query = fields.get("query", "")
        edition_id = _integer(fields["edition_id"]) if fields.get("edition_id") else None
        return private(
            render(
                request,
                "source_rights/desk.html",
                services.desk(**common, query=query, edition_id=edition_id),
            )
        )
    except (InvalidForm, SuspiciousOperation):
        return denied("source_rights_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("source_rights_action_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("source_rights_store_unavailable", 503)
