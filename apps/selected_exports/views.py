"""Native private selection, preview, durable job controls and authenticated download."""

import uuid
from contextlib import ExitStack

from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _integer, _provider
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import policy, resources, services

FIELDS = {
    "exports_open": set(),
    "exports_search": {"kind", "query", "edition_id"},
    "exports_prepare": {"selection", "state", "format", "include_files"},
    "exports_job": {"job_id"},
    "exports_preview": {"job_id"},
    "exports_queue": {"job_id", "revision", "request_key"},
    "exports_cancel": {"job_id", "revision", "request_key"},
    "exports_build": {"job_id", "request_key"},
    "exports_download": {"job_id", "request_key"},
}
ACTIONS = frozenset(FIELDS)
SALT = "fatwa.selected-exports.selection.v1"


def _form(request, action):
    fields = request.POST
    required = FIELDS[action] | {"action", "case_ref", "csrfmiddlewaretoken"}
    if request.content_type != "application/x-www-form-urlencoded" or set(fields) != required:
        raise InvalidForm("export_fields")
    for key in fields:
        limit = services.MAX_ITEMS if action == "exports_prepare" and key == "selection" else 1
        if not 1 <= len(fields.getlist(key)) <= limit:
            raise InvalidForm("export_fields")
    return fields


def _binding(request, common, case_ref):
    actor = cases._identity(
        common["provider"], common["subject_id"], Case.objects.get(pk=common["case_id"])
    )
    return browser_proof(
        request,
        SALT,
        "|".join((common["provider"].provider_id, actor.subject_id, actor.auth_epoch, case_ref)),
    )


def _page(
    request,
    common,
    *,
    kind="REFERENCE",
    query="",
    edition_id=None,
    job_id=None,
    preview=False,
    message="",
):
    kinds = resources.MEDIA if kind == "MEDIA" else {kind}
    with ExitStack() as stack:
        stack.enter_context(policy.boundary(**common, kinds=kinds))
        if job_id and preview:
            stack.enter_context(
                services.job_boundary(job_id=job_id, action="PREPARE", source_policy=True, **common)
            )
        context = services.inventory(**common, kind=kind, query=query, edition_id=edition_id)
        context.update(services.jobs(**common), message=message)
        if job_id:
            context["selected_job"] = (
                services.preview(job_id=job_id, **common)
                if preview
                else services.status(job_id=job_id, **common)
            )
        get_token(request)
        context["state"] = signing.dumps(
            {
                "binding": _binding(request, common, context["case_ref"]),
                "case_ref": context["case_ref"],
                "revision": context["revision"],
                "evidence_version": context["evidence_version"],
                "resources": [row["resource"] for row in context["rows"]],
                "request_key": str(uuid.uuid4()),
            },
            salt=SALT,
            compress=True,
        )
        for row in context["jobs"]:
            row["request_key"] = str(uuid.uuid4())
        if context.get("selected_job"):
            context["selected_job"]["request_key"] = str(uuid.uuid4())
        response = private(render(request, "selected_exports/desk.html", context))
        # Native template construction remains within the policy boundary. All
        # displayed sources are re-read before its final pure epoch/ledger check.
        services.inventory(**common, kind=kind, query=query, edition_id=edition_id)
        if job_id and preview:
            services.preview(job_id=job_id, **common)
        return response


@csrf_protect
def entry(request):
    try:
        policy.enabled()
        if request.method not in {"GET", "HEAD"} or request.GET:
            raise InvalidForm("export_entry")
        directory = _provider()
        actor = current_staff(request, directory)
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        rows = cases.list_cases(**common)
        with ExitStack() as stack:
            allowed = []
            for row in sorted(rows, key=lambda row: row["case_id"]):
                try:
                    stack.enter_context(policy.boundary(**common, case_id=row["case_id"]))
                except cases.CaseConflict:
                    continue
                allowed.append({"case_ref": row["public_ref"]})
            get_token(request)
            return private(render(request, "selected_exports/entry.html", {"cases": allowed}))
    except (InvalidForm, SuspiciousOperation):
        return denied("export_form_invalid", 400)
    except (IdentityUnavailable, cases.CaseConflict):
        return denied("export_access_required", 403)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("export_store_unavailable", 503)


@sensitive_post_parameters("state")
@csrf_protect
def workspace(request):
    try:
        policy.enabled()
        action = request.POST.get("action", "")
        if request.method != "POST" or action not in ACTIONS or request.GET:
            raise InvalidForm("export_form")
        fields = _form(request, action)
        directory = _provider()
        actor = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        row = next(
            (row for row in cases.list_cases(**common) if row["public_ref"] == fields["case_ref"]),
            None,
        )
        if row is None:
            return denied("export_case_unavailable", 404)
        common["case_id"] = row["case_id"]
        if action == "exports_search":
            return _page(
                request,
                common,
                kind=fields["kind"],
                query=fields["query"],
                edition_id=_integer(fields["edition_id"]) if fields["edition_id"] else None,
            )
        if action == "exports_prepare":
            state = signing.loads(fields["state"], salt=SALT, max_age=900)
            if state["case_ref"] != fields["case_ref"] or state["binding"] != _binding(
                request, common, fields["case_ref"]
            ):
                raise InvalidForm("export_binding")
            indices = fields.getlist("selection")
            if len(set(indices)) != len(indices) or fields["include_files"] not in {"yes", "no"}:
                raise InvalidForm("export_selection")
            if any(
                not value.isdecimal()
                or str(int(value)) != value
                or int(value) >= len(state["resources"])
                for value in indices
            ):
                raise InvalidForm("export_selection")
            job = services.prepare(
                **common,
                selected=[state["resources"][int(i)] for i in indices],
                format=fields["format"],
                include_files=fields["include_files"] == "yes",
                request_key=state["request_key"],
                expected_revision=state["revision"],
                expected_evidence_version=state["evidence_version"],
            )
            return _page(
                request,
                common,
                job_id=job["id"],
                preview=True,
                message="حُفظ نطاق المعاينة. راجع المواد والملفات ثم أكد وضع المهمة في قائمة التجهيز.",
            )
        if action in {"exports_job", "exports_preview"}:
            return _page(
                request, common, job_id=fields["job_id"], preview=action == "exports_preview"
            )
        if action in {"exports_queue", "exports_cancel"}:
            services.command(
                **common,
                job_id=fields["job_id"],
                action="QUEUE" if action == "exports_queue" else "CANCEL",
                request_key=fields["request_key"],
                expected_revision=_integer(fields["revision"]),
            )
            return _page(request, common, job_id=fields["job_id"])
        if action == "exports_build":
            services.run_job(**common, job_id=fields["job_id"], request_key=fields["request_key"])
            return _page(request, common, job_id=fields["job_id"])
        if action == "exports_download":
            with services.job_boundary(
                **common, job_id=fields["job_id"], action="DOWNLOAD", source_policy=True
            ):
                result = services.download(
                    **common, job_id=fields["job_id"], request_key=fields["request_key"]
                )
                response = private(HttpResponse(result["raw"], content_type="application/zip"))
                response["Content-Disposition"] = f'attachment; filename="{result["filename"]}"'
                response["X-Export-SHA256"] = result["sha256"]
                response["X-Export-Result"] = "partial" if result["partial"] else "complete"
                return response
        return _page(request, common)
    except cases.CaseConflict:
        return denied("export_action_not_accepted", 409)
    except (
        InvalidForm,
        SuspiciousOperation,
        signing.BadSignature,
        KeyError,
        TypeError,
        ValueError,
    ):
        return denied("export_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("export_store_unavailable", 503)
