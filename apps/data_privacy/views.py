"""Native CSRF-bound management for the current Mufti or operational identity."""

import uuid
from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web import access
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.operational_workspace import access as operational_access
from apps.operational_workspace import identity

from . import integration, management, services
from .catalog import LEVELS, digest

STAFF_PATH = "/casework/staff/privacy/"
OPERATIONAL_PATH = "/casework/operations/privacy/"
ACTIONS = {"privacy_open", "privacy_inspect", "privacy_classify"}
LEVEL_LABELS = {"PUBLIC": "عام", "INTERNAL": "داخلي", "CONFIDENTIAL": "سري", "RESTRICTED": "مقيد"}


def _common(request):
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if request.path == OPERATIONAL_PATH:
        actor, until = operational_access.current(request, directory)
        provider = identity.RequestDirectory(directory, actor)
    elif request.path == STAFF_PATH:
        actor = access.current_staff(request, directory)
        until = actor.valid_until
        provider = access.RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
    else:
        raise InvalidForm("privacy_path_invalid")
    return dict(
        provider=provider,
        subject_id=actor.subject_id,
        synthetic_fixtures_only=True,
        session_deadline=until,
    )


def _fields(request):
    if request.GET or request.FILES or request.method not in {"GET", "POST"}:
        raise InvalidForm("privacy_form_invalid")
    if request.method == "GET":
        return {"action": "privacy_open"}
    action = request.POST.get("action")
    expected = {"action"}
    if action in {"privacy_inspect", "privacy_classify"}:
        expected |= {"kind", "identifier"}
    if action == "privacy_classify":
        expected |= {
            "level",
            "note",
            "expected_digest",
            "source_digest",
            "request_key",
            "proof",
            "confirmed",
        }
    if (
        action not in ACTIONS
        or request.content_type != "application/x-www-form-urlencoded"
        or set(request.POST) != expected | {"csrfmiddlewaretoken"}
        or any(len(values) != 1 for _, values in request.POST.lists())
    ):
        raise InvalidForm("privacy_form_invalid")
    return {name: request.POST[name] for name in expected}


def _proof(request, common, kind, identifier, source, previous):
    actor = common["provider"].resolve(common["subject_id"])
    payload = digest(
        [
            common["provider"].provider_id,
            actor.subject_id,
            actor.role,
            actor.auth_epoch,
            kind,
            str(identifier),
            source,
            previous,
        ]
    )
    return browser_proof(request, "fatwa.privacy.classification.v1", payload)


@sensitive_post_parameters("note")
@csrf_protect
def workspace(request):
    try:
        fields = _fields(request)
        common = _common(request)
        # Authentication has finished. Keep this native management operation and
        # its actual template render in one short owned transaction. No external
        # candidate provider or fresh-authentication call runs in this scope.
        with integration.projection():
            if fields["action"] == "privacy_open":
                catalog = management.catalog(**common)
                return private(render(request, "data_privacy/desk.html", {"catalog": catalog}))
            if fields["action"] == "privacy_classify":
                if fields["confirmed"] != "yes" or not compare_digest(
                    fields["proof"],
                    _proof(
                        request,
                        common,
                        fields["kind"],
                        fields["identifier"],
                        fields["source_digest"],
                        fields["expected_digest"],
                    ),
                ):
                    raise InvalidForm("privacy_browser_proof_invalid")
                services.classify(
                    kind=fields["kind"],
                    identifier=fields["identifier"],
                    level=fields["level"],
                    note=fields["note"],
                    expected_digest=fields["expected_digest"],
                    expected_source_digest=fields["source_digest"],
                    request_key=fields["request_key"],
                    **common,
                )
            with management.inspect(
                kind=fields["kind"], identifier=fields["identifier"], **common
            ) as item:
                return private(
                    render(
                        request,
                        "data_privacy/item.html",
                        {
                            "item": item,
                            "request_key": str(uuid.uuid4()),
                            "levels": [(value, LEVEL_LABELS[value]) for value in LEVELS],
                            "proof": _proof(
                                request,
                                common,
                                item["kind"],
                                item["id"],
                                item["source_digest"],
                                item["digest"],
                            ),
                            "saved": fields["action"] == "privacy_classify",
                        },
                    )
                )
    except IdentityUnavailable:
        return denied("privacy_current_session_required", 403)
    except (services.PrivacyDenied, cases.CaseConflict):
        return denied("privacy_management_unavailable", 404)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError):
        return denied("privacy_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("privacy_store_unavailable", 503)
