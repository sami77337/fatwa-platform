"""Explicit POST actions composed into the existing guarded staff URL."""

from django.conf import settings
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
from apps.mufti_review.identity import IdentityUnavailable

from . import services

ACTIONS = {
    "pub_open",
    "pub_correct",
    "pub_create",
    "pub_review",
    "pub_approve",
    "pub_withdraw",
    "pub_library",
    "pub_read",
}


@sensitive_post_parameters("body", "title", "query")
@csrf_protect
def workspace(request):
    try:
        services._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("publication_form_invalid")
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        action = request.POST.get("action")
        required = {"action", "query"} if action == "pub_library" else {"action", "case_ref"}
        if action == "pub_library" and "category" in request.POST:
            required.add("category")
        if action == "pub_read":
            required = {"action", "edition_id"}
            if "query" in request.POST or "category" in request.POST:
                required |= {"query", "category"}
        if action == "pub_correct":
            required.add("edition_id")
        if action == "pub_create":
            required |= {"revision", "evidence_version", "title", "category", "body"}
            if "source_edition_id" in request.POST:
                required.add("source_edition_id")
        elif action in {"pub_review", "pub_approve", "pub_withdraw"}:
            required |= {"edition_id", "confirm"}
        fields = _form(request, required)
        if request.FILES:
            raise InvalidForm("publication_form_invalid")
        common = {
            "subject_id": identity.subject_id,
            "provider": provider,
            "synthetic_fixtures_only": True,
        }
        get_token(request)
        if action == "pub_library":
            return private(
                render(
                    request,
                    "experimental_publication/library.html",
                    {
                        "publications": services.library(
                            **common, query=fields["query"], category=fields.get("category", "")
                        ),
                        "categories": sorted(
                            {row["category"] for row in services.library(**common)}
                        ),
                        "query": fields["query"],
                        "category": fields.get("category", ""),
                    },
                )
            )
        if action == "pub_read":
            for key in ("query", "category"):
                if len(fields.get(key, "")) > 80:
                    raise InvalidForm("publication_form_invalid")
            edition = next(
                (row for row in services.library(**common) if row["id"] == fields["edition_id"]),
                None,
            )
            if edition is None:
                return denied("publication_unavailable", 404)
            return private(
                render(
                    request,
                    "experimental_publication/detail.html",
                    {
                        "edition": edition,
                        "knowledge_enabled": getattr(settings, "FATWA_KNOWLEDGE_LINKS_ENABLED", False) is True,
                        "query": fields.get("query", ""),
                        "category": fields.get("category", ""),
                    },
                )
            )
        scoped = cases.list_cases(**common)
        selected = next((row for row in scoped if row["public_ref"] == fields["case_ref"]), None)
        if selected is None:
            return denied("publication_unavailable", 404)
        common["case_id"] = selected["case_id"]
        correction = None
        if action == "pub_correct":
            correction = services.correction_draft(**common, edition_id=fields["edition_id"])
        elif action == "pub_create":
            services.create_edition(
                **common,
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
                title=fields["title"],
                category=fields["category"],
                body=fields["body"],
                source_edition_id=fields.get("source_edition_id"),
            )
        elif action != "pub_open":
            if fields["confirm"] != "yes":
                raise InvalidForm("publication_confirmation_required")
            services.act(
                **common,
                edition_id=fields["edition_id"],
                action={
                    "pub_review": "REVIEW",
                    "pub_approve": "APPROVE",
                    "pub_withdraw": "WITHDRAW",
                }[action],
                reviewed=True,
            )
        return private(
            render(
                request,
                "experimental_publication/desk.html",
                {
                    "selected": services.desk(**common),
                    "saved": action not in {"pub_open", "pub_correct"},
                    "correction": correction,
                },
            )
        )
    except (InvalidForm, SuspiciousOperation):
        return denied("publication_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("publication_action_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("publication_store_unavailable", 503)
