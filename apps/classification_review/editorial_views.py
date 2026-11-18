"""Closed native-form simulation over canonical editorial services."""

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import MaintenanceUnavailable

from . import editorial

ACTIONS = {
    "classification_editorial_prepare",
    "classification_editorial_inspect",
    "classification_editorial_review",
    "classification_editorial_approve",
}


@csrf_protect
def workspace(request):
    try:
        editorial._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("classification_editorial_form_invalid")
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        action = request.POST.get("action")
        fields = {"action", "publication_id"}
        if action == "classification_editorial_prepare":
            fields |= {"revision_id", "expected_revision", "expected_evidence_version", "confirm"}
        else:
            fields |= {"binding_id"}
            if action != "classification_editorial_inspect":
                fields |= {"confirm"}
        fields = _form(request, fields)
        if request.FILES:
            raise InvalidForm("classification_editorial_form_invalid")
        common = dict(
            publication_id=fields["publication_id"],
            subject_id=identity.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        if action == "classification_editorial_prepare":
            result = editorial.prepare_edition(
                **common,
                revision_id=fields["revision_id"],
                expected_revision=_integer(fields["expected_revision"]),
                expected_evidence_version=_integer(fields["expected_evidence_version"]),
                confirmed=fields["confirm"] == "yes",
            )
            binding_id = result["binding_id"]
        else:
            binding_id = fields["binding_id"]
            if action != "classification_editorial_inspect":
                editorial.act(
                    **common,
                    binding_id=binding_id,
                    confirmed=fields["confirm"] == "yes",
                    action="REVIEW" if action == "classification_editorial_review" else "APPROVE",
                )
        context = editorial.inspect(**common, binding_id=binding_id)
        request.classification_authorized_case_ref = context["public_ref"]
        return private(render(request, "classification_review/editorial.html", context))
    except (InvalidForm, SuspiciousOperation):
        return denied("classification_editorial_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("classification_editorial_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied, MaintenanceUnavailable):
        return denied("classification_editorial_store_unavailable", 503)
