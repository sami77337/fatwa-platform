"""Native provisional-tree editing, human mapping review and exact rollback."""

import re
import uuid

from django.core import signing
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

from . import services
from .boundary import digest, scope

ACTIONS = frozenset(
    {
        "dt_open",
        "dt_save",
        "dt_review",
        "dt_bind",
        "dt_prepare",
        "dt_apply",
        "dt_rollback",
        "dt_history",
    }
)
COMMON = {"action", "case_ref", "csrfmiddlewaretoken"}
PINS = {*COMMON, "state"}
FIELDS = {
    "dt_open": {*COMMON, "version_id"},
    "dt_history": {*COMMON, "version_id"},
    "dt_save": {
        *PINS,
        "version_id",
        "title",
        "provenance",
        "node_key",
        "node_name",
        "node_parent",
        "node_definition",
        "reason",
        "confirmed",
        "command",
    },
    "dt_review": {
        *PINS,
        "version_id",
        "target_kind",
        "target_id",
        "decision",
        "reason",
        "confirmed",
    },
    "dt_bind": {*PINS, "version_id", "primary", "additional", "reason", "confirmed"},
    "dt_apply": {*PINS, "plan_id", "reason", "confirmed"},
    "dt_rollback": {*PINS, "plan_id", "reason", "confirmed"},
}
PREPARE_FIELDS = {
    "choose": {*PINS, "command", "source_version_id", "target_version_id"},
    "impact": {*PINS, "command", "source_version_id", "target_version_id"},
    "plan": {*PINS, "command", "impact", "reason", "confirmed"},
}
DYNAMIC = re.compile(
    r"(?:map_kind|map_target|map_reason|resolution_primary|resolution_additional|resolution_hold|resolution_reason)_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
MULTIPLE = {"node_key", "node_name", "node_parent", "node_definition", "additional"}


def _audience(request, actor, provider, case_id):
    get_token(request)
    return digest(
        [
            str(case_id),
            provider.provider_id,
            actor.subject_id,
            actor.auth_epoch,
            request.META.get("CSRF_COOKIE", ""),
        ]
    )


def _seal(value, audience, salt):
    return signing.dumps({"value": value, "audience": audience}, salt=salt, compress=True)


def _open(value, audience, salt):
    if type(value) is not str or not 1 <= len(value) <= 96000:
        raise cases.CaseConflict("development_taxonomy_form_invalid")
    try:
        result = signing.loads(value, salt=salt, max_age=600)
    except signing.BadSignature as exc:
        raise cases.CaseConflict("development_taxonomy_form_expired") from exc
    if result.get("audience") != audience or type(result.get("value")) is not dict:
        raise cases.CaseConflict("development_taxonomy_form_audience")
    return result["value"]


def draft_nodes(post):
    keys = post.getlist("node_key")
    columns = [post.getlist(name) for name in ("node_name", "node_parent", "node_definition")]
    if not 1 <= len(keys) <= services.MAX_NODES or any(
        len(column) != len(keys) for column in columns
    ):
        raise cases.CaseConflict("development_taxonomy_draft_invalid")
    return [
        {"key": key, "name": name, "parent": parent, "definition": definition}
        for key, name, parent, definition in zip(keys, *columns, strict=True)
    ]


def mapping_form(guard, source_id, target_id):
    source = services._version(guard, source_id, reviewed=True, action="MAP")
    target = services._version(guard, target_id, reviewed=True, action="MAP")
    if source.tree_id != target.tree_id or source.number >= target.number:
        raise cases.CaseConflict("development_taxonomy_mapping_invalid")
    old, new = services.validate_tree(source.nodes), services.validate_tree(target.nodes)
    rows = []
    for key, node in old.items():
        kind = "NO_EQUIVALENT"
        if key in new:
            kind = (
                "RENAMED"
                if node["name"] != new[key]["name"]
                else "MOVED"
                if (node["parent"], node["order"]) != (new[key]["parent"], new[key]["order"])
                else "SAME"
            )
        rows.append(
            {
                "source": key,
                "name": node["name"],
                "kind": kind,
                "targets": [key] if key in new else [],
                "reason": "",
            }
        )
    return {
        "source_version_id": str(source.pk),
        "target_version_id": str(target.pk),
        "source_number": source.number,
        "target_number": target.number,
        "rows": rows,
        "targets": target.nodes,
        "kinds": services.MAPPING_KINDS,
    }


def page(
    request,
    base,
    actor,
    provider,
    *,
    version_id=None,
    draft=None,
    mapping=None,
    impact=None,
    message="",
    title="",
    provenance="",
):
    with scope(**base) as guard:
        result = services.desk_locked(guard, case_id=base["case_id"], version_id=version_id)
        selected = result["selected"]
        audience = _audience(request, actor, provider, base["case_id"])
        state = {
            "expected_snapshot": result["snapshot"],
            "expected_revision": result["revision"],
            "expected_evidence_version": result["evidence_version"],
            "request_key": str(uuid.uuid4()),
            "tree_id": selected["tree_id"] if selected else None,
            "expected_number": selected["number"] if selected else 0,
        }
        if draft is None:
            draft = (
                [
                    {
                        "key": node["id"],
                        "name": node["name"],
                        "parent": node["parent"] or "",
                        "definition": node["definition"],
                    }
                    for node in selected["nodes"]
                ]
                if selected
                else []
            )
            draft += [
                {"key": f"new:{index}", "name": "", "parent": "", "definition": ""}
                for index in range(min(4, services.MAX_NODES - len(draft)))
            ]
        if mapping:
            # Re-resolve both versions while the actual form is rendered.
            services._version(guard, mapping["source_version_id"], reviewed=True, action="MAP")
            services._version(guard, mapping["target_version_id"], reviewed=True, action="MAP")
        if impact:
            current = services.preview_locked(
                guard,
                source_version_id=impact["source_version_id"],
                target_version_id=impact["target_version_id"],
                mapping=impact["mapping"],
            )
            if current != impact:
                raise cases.CaseConflict("development_taxonomy_impact_changed")
        return private(
            render(
                request,
                "development_taxonomy/desk.html",
                {
                    "result": result,
                    "draft": draft,
                    "title": selected["title"] if selected else title,
                    "provenance": selected["provenance"] if selected else provenance,
                    "state": _seal(state, audience, "development-taxonomy-state.v1"),
                    "mapping": mapping,
                    "impact": impact,
                    "impact_token": _seal(impact, audience, "development-taxonomy-impact.v1")
                    if impact
                    else "",
                    "message": message,
                },
            )
        )


@mutation_service
@sensitive_post_parameters("state", "reason", "provenance", "impact")
@csrf_protect
def workspace(request):
    try:
        action = request.POST.get("action")
        command = request.POST.get("command")
        fields = (
            PREPARE_FIELDS.get(command, set())
            if action == "dt_prepare"
            else FIELDS.get(action, set())
        )
        prefix = (
            "map_"
            if action == "dt_prepare" and command == "impact"
            else "resolution_"
            if action == "dt_prepare" and command == "plan"
            else None
        )
        if (
            request.method != "POST"
            or request.FILES
            or action not in ACTIONS
            or not fields
            or any(
                key not in fields
                and not (prefix and key.startswith(prefix) and DYNAMIC.fullmatch(key))
                for key in request.POST
            )
        ):
            raise InvalidForm("development_taxonomy_form_invalid")
        if any(
            len(values) != 1
            for key, values in request.POST.lists()
            if key not in MULTIPLE and not key.startswith(("map_target_", "resolution_additional_"))
        ):
            raise InvalidForm("development_taxonomy_form_invalid")
        directory = _provider()
        actor = current_staff(request, directory)
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        case = Case.objects.filter(
            public_ref=request.POST.get("case_ref"), public_ref__in=actor.case_keys
        ).first()
        if case is None:
            return denied("development_taxonomy_unavailable", 404)
        base = dict(
            case_id=case.pk,
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        with synthetic_queue_atomic():
            if action in {"dt_open", "dt_history"}:
                return page(
                    request,
                    base,
                    actor,
                    provider,
                    version_id=request.POST.get("version_id") or None,
                )
            audience = _audience(request, actor, provider, case.pk)
            state = _open(request.POST.get("state"), audience, "development-taxonomy-state.v1")
            versions = {
                key: value
                for key, value in state.items()
                if key not in {"tree_id", "expected_number"}
            }
            common = {**base, **versions}
            confirmed = request.POST.get("confirmed") == "yes"
            if action == "dt_save":
                draft = draft_nodes(request.POST)
                if request.POST.get("command") == "add":
                    used = {row["key"] for row in draft}
                    index = 0
                    target_size = min(len(draft) + 4, services.MAX_NODES)
                    while len(draft) < target_size:
                        key = f"new:{index}"
                        index += 1
                        if key not in used:
                            draft.append({"key": key, "name": "", "parent": "", "definition": ""})
                            used.add(key)
                    return page(
                        request,
                        base,
                        actor,
                        provider,
                        version_id=request.POST.get("version_id") or None,
                        draft=draft,
                        title=request.POST.get("title", ""),
                        provenance=request.POST.get("provenance", ""),
                    )
                row = services.save_version(
                    **common,
                    tree_id=state["tree_id"],
                    expected_number=state["expected_number"],
                    title=request.POST.get("title", ""),
                    provenance=request.POST.get("provenance", ""),
                    nodes=[row for row in draft if row["name"].strip()],
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
                return page(
                    request,
                    base,
                    actor,
                    provider,
                    version_id=row["id"],
                    message="حُفظت نسخة مؤقتة مستقلة للمراجعة؛ لا اعتماد لشجرة شرعية نهائية.",
                )
            if action == "dt_review":
                services.review(
                    **common,
                    target_kind=request.POST.get("target_kind"),
                    target_id=request.POST.get("target_id"),
                    action=request.POST.get("decision"),
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
            elif action == "dt_bind":
                services.bind(
                    **common,
                    version_id=request.POST.get("version_id"),
                    primary=request.POST.get("primary"),
                    additional=request.POST.getlist("additional"),
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
            elif action == "dt_prepare":
                command = request.POST.get("command")
                if command in {"choose", "impact"}:
                    with scope(**base) as guard:
                        form = mapping_form(
                            guard,
                            request.POST.get("source_version_id"),
                            request.POST.get("target_version_id"),
                        )
                    if command == "choose":
                        return page(request, base, actor, provider, mapping=form)
                    allowed = {
                        prefix + row["source"]
                        for row in form["rows"]
                        for prefix in ("map_kind_", "map_target_", "map_reason_")
                    }
                    if any(key not in fields | allowed for key in request.POST):
                        raise InvalidForm("development_taxonomy_mapping_fields")
                    mapping = [
                        {
                            "source": row["source"],
                            "kind": request.POST.get("map_kind_" + row["source"]),
                            "targets": request.POST.getlist("map_target_" + row["source"]),
                            "reason": request.POST.get("map_reason_" + row["source"], ""),
                        }
                        for row in form["rows"]
                    ]
                    impact = services.preview(
                        **base,
                        source_version_id=form["source_version_id"],
                        target_version_id=form["target_version_id"],
                        mapping=mapping,
                    )
                    if impact["snapshot"] != state["expected_snapshot"]:
                        raise cases.CaseConflict("development_taxonomy_version_changed")
                    return page(request, base, actor, provider, impact=impact)
                if command != "plan":
                    raise InvalidForm("development_taxonomy_form_invalid")
                impact = _open(
                    request.POST.get("impact"), audience, "development-taxonomy-impact.v1"
                )
                allowed = {
                    prefix + item["case_id"]
                    for item in impact["impacts"]
                    for prefix in (
                        "resolution_primary_",
                        "resolution_additional_",
                        "resolution_hold_",
                        "resolution_reason_",
                    )
                }
                if any(key not in fields | allowed for key in request.POST):
                    raise InvalidForm("development_taxonomy_resolution_fields")
                resolutions = [
                    {
                        "case_id": item["case_id"],
                        "hold": request.POST.get("resolution_hold_" + item["case_id"]) == "yes",
                        "primary": request.POST.get("resolution_primary_" + item["case_id"], ""),
                        "additional": request.POST.getlist(
                            "resolution_additional_" + item["case_id"]
                        ),
                        "reason": request.POST.get("resolution_reason_" + item["case_id"], ""),
                    }
                    for item in impact["impacts"]
                ]
                services.save_plan(
                    **common,
                    source_version_id=impact["source_version_id"],
                    target_version_id=impact["target_version_id"],
                    mapping=impact["mapping"],
                    resolutions=resolutions,
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
            else:
                services.execute(
                    **common,
                    plan_id=request.POST.get("plan_id"),
                    kind="APPLY" if action == "dt_apply" else "ROLLBACK",
                    reason=request.POST.get("reason", ""),
                    confirmed=confirmed,
                )
            return page(
                request,
                base,
                actor,
                provider,
                version_id=request.POST.get("version_id") or None,
                message="حُفظ الإجراء البشري مع النسخ والأثر؛ بقيت الأصول والأحكام كما هي.",
            )
    except (
        cases.CaseConflict,
        IdentityUnavailable,
        InvalidForm,
        SyntheticWriteDenied,
        DatabaseError,
        ValueError,
        KeyError,
    ):
        return denied("development_taxonomy_action_unavailable", 409)
