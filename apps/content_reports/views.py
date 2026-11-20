"""Native reporting and triage forms on the existing scoped staff endpoint."""

import uuid

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

FIELDS = {
    "reports_open": set(),
    "report_prepare": {"target_kind", "target_id"},
    "report_submit": {
        "target_kind",
        "target_id",
        "selected_target",
        "revision",
        "evidence_version",
        "request_key",
        "reason",
        "description",
        "evidence_note",
    },
    "report_advance": {
        "report_id",
        "report_revision",
        "request_key",
        "transition",
        "action_note",
        "verification_note",
        "related_report_id",
    },
}
ACTIONS = frozenset(FIELDS)


def _page(request, common, *, selected=None, message=""):
    with services.staff_projection_boundary(
        **common, source_kind=selected["target"]["kind"] if selected else None
    ):
        context = services.staff_desk(**common)
        if selected:
            fresh = services.prepare_staff_target(
                **common,
                target_kind=selected["target"]["kind"],
                target_id=selected["target"]["identifier"],
            )
            if fresh != selected:
                raise cases.CaseConflict("report_target_changed")
        for row in context["reports"]:
            row["request_key"] = str(uuid.uuid4())
            row["link_key"] = str(uuid.uuid4())
        context.update(selected=selected, message=message, request_key=str(uuid.uuid4()))
        get_token(request)
        return private(render(request, "content_reports/desk.html", context))


@sensitive_post_parameters()
@csrf_protect
def workspace(request):
    try:
        services.enabled()
        action = request.POST.get("action", "")
        if request.method != "POST" or action not in ACTIONS or request.GET:
            raise InvalidForm("reports_form_invalid")
        fields = _form(request, {"action", "case_ref"} | FIELDS[action])
        directory = _provider()
        actor = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        selected_case = next(
            (row for row in cases.list_cases(**common) if row["public_ref"] == fields["case_ref"]),
            None,
        )
        if selected_case is None:
            return denied("report_case_unavailable", 404)
        common["case_id"] = selected_case["case_id"]
        if action == "report_prepare":
            selected = services.prepare_staff_target(
                **common, target_kind=fields["target_kind"], target_id=fields["target_id"]
            )
            return _page(request, common, selected=selected)
        if action == "report_submit":
            services.submit_staff(
                **common,
                target_kind=fields["target_kind"],
                target_id=fields["target_id"],
                selected_target=fields["selected_target"],
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
                request_key=fields["request_key"],
                reason=fields["reason"],
                description=fields["description"],
                evidence_note=fields["evidence_note"],
            )
            return _page(
                request,
                common,
                message="استُلم البلاغ للمراجعة؛ لم يُصلح أو يُعدّل المحتوى بهذه الخطوة.",
            )
        if action == "report_advance":
            services.advance(
                **common,
                report_id=fields["report_id"],
                expected_revision=_integer(fields["report_revision"]),
                request_key=fields["request_key"],
                action=fields["transition"],
                action_note=fields["action_note"],
                verification_note=fields["verification_note"],
                related_report_id=fields["related_report_id"],
            )
            return _page(
                request, common, message="حُفظ إجراء المراجعة في سجل البلاغ. لم يتغير المحتوى."
            )
        return _page(request, common)
    except (InvalidForm, SuspiciousOperation):
        return denied("report_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("report_action_not_accepted", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("report_store_unavailable", 503)
