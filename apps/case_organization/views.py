"""Native internal metadata editor and explicit authorized tag/type search."""

import uuid

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services

ACTIONS = {"organization_open", "organization_save", "organization_search"}


def _fields(request):
    required = {
        "action",
        "case_ref",
        "revision",
        "evidence_version",
        "metadata_version",
        "command_id",
        "tags",
        "note",
    }
    fields = request.POST
    if (
        request.content_type != "application/x-www-form-urlencoded"
        or set(fields) - {"question_types"} != required | {"csrfmiddlewaretoken"}
        or any(len(fields.getlist(key)) != 1 for key in fields if key != "question_types")
    ):
        raise InvalidForm("organization_form_invalid")
    return fields


def _page(request, common, *, status=200, error="", attempted=None):
    result = services.snapshot(**common)
    return private(
        render(
            request,
            "case_organization/desk.html",
            {
                "organization": result,
                "error": error,
                "attempted": attempted,
                "command_id": str(uuid.uuid4()),
                "types": [
                    {"key": key, "label": label, "selected": key in result["question_types"]}
                    for key, label in services.QUESTION_TYPES.items()
                ],
            },
            status=status,
        )
    )


@sensitive_post_parameters("tags", "note")
@csrf_protect
def workspace(request):
    try:
        services._enabled()
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS or request.FILES:
            raise InvalidForm("organization_form_invalid")
        if action == "organization_save":
            fields = _fields(request)
        elif action == "organization_search":
            fields = _form(request, {"action", "query", "tag", "question_type"})
        else:
            fields = _form(request, {"action", "case_ref"})
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        common = dict(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        if action == "organization_search":
            result = services.search(
                **common,
                query=fields["query"],
                tag=fields["tag"],
                question_type=fields["question_type"],
            )
            return private(
                render(
                    request,
                    "case_organization/search.html",
                    {
                        "rows": result,
                        "query": fields["query"],
                        "tag": fields["tag"],
                        "question_type": fields["question_type"],
                        "types": services.QUESTION_TYPES.items(),
                    },
                )
            )
        rows = cases.list_cases(**common)
        selected = next((row for row in rows if row["public_ref"] == fields["case_ref"]), None)
        if selected is None:
            return denied("organization_unavailable", 404)
        common["case_id"] = selected["case_id"]
        if action == "organization_save":
            raw_version = fields["metadata_version"]
            metadata_version = 0 if raw_version == "0" else _integer(raw_version)
            # Newline separation keeps human tag text intact; no inference/AI expansion.
            tags = [value.strip() for value in fields["tags"].splitlines() if value.strip()]
            try:
                services.save(
                    **common,
                    tags=tags,
                    question_types=fields.getlist("question_types"),
                    note=fields["note"],
                    command_id=fields["command_id"],
                    expected_metadata_version=metadata_version,
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                )
            except cases.CaseConflict:
                # Fresh authorization precedes rendering rejected private text.
                return _page(
                    request,
                    common,
                    status=409,
                    error="لم يُحفظ التعديل. راجع النسخة الحالية والمحاولة أدناه ثم أعد الإدخال صراحة.",
                    attempted={"tags": fields["tags"][:1000], "note": fields["note"][:2000]},
                )
        return _page(request, common)
    except (InvalidForm, SuspiciousOperation):
        return denied("organization_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("organization_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("organization_store_unavailable", 503)
