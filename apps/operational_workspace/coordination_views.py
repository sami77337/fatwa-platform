"""Strict native forms for the human administrative coordination boundary."""

from django.shortcuts import render

from apps.casework.services import CaseConflict

from . import coordination


def dispatch(request, action, common):
    from .views import form, integer

    if action == "coordination":
        form(request, {"action", "case_ref"})
        operation = coordination.projection(case_ref=request.POST.get("case_ref"), **common)
    else:
        base = {
            "action",
            "case_ref",
            "reason",
            "confirmed",
            "command_id",
            "version",
            "revision",
            "evidence_version",
        }
        if action in {"coordination_set", "coordination_clear"}:
            form(request, base | {"target_subject", "target_epoch"})
        elif action == "coordination_priority":
            form(request, base | {"priority", "policy_sha256"})
        else:
            raise CaseConflict("operational_action_unavailable")
        values = dict(
            case_ref=request.POST.get("case_ref"),
            reason=request.POST.get("reason"),
            confirmed=request.POST.get("confirmed") == "yes",
            command_id=request.POST.get("command_id"),
            expected_version=integer(request, "version"),
            expected_revision=integer(request, "revision"),
            expected_evidence_version=integer(request, "evidence_version"),
            **common,
        )
        if action == "coordination_priority":
            operation = coordination.set_priority(
                value=request.POST.get("priority"),
                policy_sha256=request.POST.get("policy_sha256"),
                **values,
            )
        else:
            operation = coordination.assign(
                action="SET_PRIMARY" if action == "coordination_set" else "CLEAR_PRIMARY",
                target_subject=request.POST.get("target_subject"),
                target_epoch=request.POST.get("target_epoch", ""),
                **values,
            )
    with operation as result:
        return render(request, "operational_workspace/coordination.html", {"coordination": result})
