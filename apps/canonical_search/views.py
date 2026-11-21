"""Native Arabic forms; the complete response stays inside current source guards."""

import uuid

from django.apps import apps as django_apps
from django.conf import settings

from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.arabic_search_eval import benchmark_policy, benchmark_views
from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, resolve_identity

from . import governance_pins, governance_views, matches, policy, services, taxonomy

SALT = "fatwa.canonical-search.native.v1"
FIELDS = {
    "cs_open": set(),
    "cs_search": {"query", "mode", "kind", "page", "scope"},
    "cs_taxonomy_search": {
        "query", "mode", "kind", "page", "scope",
        "taxonomy_version", "taxonomy_node", "taxonomy_children",
    },
    "cs_rebuild": {"state"},
    "cs_source": {"state"},
    **governance_views.FIELDS,
    **benchmark_views.FIELDS,
}
ACTIONS = frozenset(FIELDS)
MODES = (
    ("LITERAL", "مطابقة حرفية للعبارة الأصلية"),
    ("FTS", "بحث نصي بالكلمات"),
    ("FUZZY", "بحث تقريبي للأخطاء الكتابية"),
)
KINDS = (
    ("ALL", "جميع النصوص المتاحة"),
    ("QUESTION", "السؤال الأصلي"),
    ("FOLLOWUP", "التعقيبات"),
    ("ANSWER", "الجواب الحالي"),
    ("TRANSCRIPT", "التفريغ المتاح"),
    ("RECORDING_TRANSCRIPT", "تفريغ مراجع مرتبط بالتسجيل"),
)


def _form(request, action):
    if (
        request.content_type != "application/x-www-form-urlencoded"
        or request.GET
        or request.FILES
        or set(request.POST) != FIELDS[action] | {"action", "case_ref", "csrfmiddlewaretoken"}
        or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
    ):
        raise InvalidForm("search_form_invalid")
    return request.POST


def _binding(request, base, case_ref):
    actor = resolve_identity(base["provider"], base["subject_id"], case_key=case_ref)
    return browser_proof(
        request,
        SALT,
        "|".join((base["provider"].provider_id, actor.subject_id, actor.auth_epoch, case_ref)),
    )


def _state(request, base, values):
    return signing.dumps(
        {**values, "binding": _binding(request, base, values["case_ref"])},
        salt=SALT,
        compress=True,
    )


def _read_state(request, base, fields):
    state = signing.loads(fields["state"], salt=SALT, max_age=900)
    if (
        type(state) is not dict
        or state.get("case_ref") != fields["case_ref"]
        or state.get("binding") != _binding(request, base, fields["case_ref"])
    ):
        raise InvalidForm("search_browser_binding")
    return state


def _page(request, base, *, search=None, selected=None, message=""):
    action = "SEARCH" if search else ("OPEN" if selected else "VIEW")
    scope = search["scope"] if search else "CASE"
    selected_filter = search if search is not None else selected or {}
    with taxonomy.reviewed_selector(
        **base,
        version_id=selected_filter.get("taxonomy_version"),
        node_id=selected_filter.get("taxonomy_node"),
        descendants=selected_filter.get("taxonomy_children", False),
    ) as taxonomy_choice, policy.boundary(**base, action=action, scope=scope) as context:
        filtered_ids = taxonomy_choice.case_ids(context.cases) if taxonomy_choice else None
        if selected and taxonomy_choice and str(base["case_id"]) not in filtered_ids:
            raise cases.CaseConflict("search_taxonomy_result_no_longer_available")
        desk = services.desk_in_context(context, case_id=base["case_id"])
        result = None
        if search:
            result = services.search_in_context(
                context,
                value=search["query"],
                mode=search["mode"],
                kind=search["kind"],
                page=search["page"],
                eligible_case_ids=filtered_ids,
                taxonomy_info=taxonomy_choice.info if taxonomy_choice else None,
            )
            for row in result["results"]:
                row["state"] = _state(
                    request,
                    base,
                    {
                        "case_ref": row["case_ref"],
                        "generation_id": row["generation_id"],
                        "document_id": row["document_id"],
                        "query": search["query"],
                        "mode": search["mode"],
                        "match_index": 0,
                        **({
                            "taxonomy_version": search["taxonomy_version"],
                            "taxonomy_node": search["taxonomy_node"],
                            "taxonomy_children": search["taxonomy_children"],
                        } if taxonomy_choice else {}),
                    },
                )
        opened = None
        if selected:
            if "query" in selected:
                opened = matches.open_in_context(
                    context,
                    case_id=base["case_id"],
                    generation_id=selected["generation_id"],
                    document_id=selected["document_id"],
                    value=selected["query"],
                    mode=selected["mode"],
                    index=selected["match_index"],
                )
                navigation = opened["navigation"]
                for direction, step in (("previous", -1), ("next", 1)):
                    if navigation[f"has_{direction}"]:
                        navigation[f"{direction}_state"] = _state(
                            request,
                            base,
                            {
                                **selected,
                                "case_ref": desk["case_ref"],
                                "match_index": navigation["index"] + step,
                            },
                        )
            else:
                # Existing dictionary/shadow source forms retain their exact
                # source-opening contract without inventing a literal query.
                opened = services.open_in_context(context, case_id=base["case_id"], **selected)
        get_token(request)
        state = _state(
            request,
            base,
            {
                "case_ref": desk["case_ref"],
                "revision": desk["revision"],
                "evidence_version": desk["evidence_version"],
                "generation": desk["generation"],
                "request_key": str(uuid.uuid4()),
            },
        )
        return private(
            render(
                request,
                "canonical_search/desk.html",
                {
                    "desk": desk,
                    "state": state,
                    "result": result,
                    "opened": opened,
                    "message": message,
                    "modes": MODES,
                    "kinds": KINDS,
                    "taxonomy_available": (
                        django_apps.is_installed("apps.development_taxonomy")
                        and getattr(settings, "FATWA_DEVELOPMENT_TAXONOMY_ENABLED", False) is True
                    ),
                    "governance_navigation": governance_pins.flag() == (bool, True),
                    "benchmark_navigation": benchmark_policy.flag() == (bool, True),
                    "values": search
                    or {
                        "query": selected.get("query", "") if selected else "",
                        "mode": selected.get("mode", "FTS") if selected else "FTS",
                        "kind": "ALL",
                        "scope": "CASE",
                        "page": 1,
                        "taxonomy_version": selected.get("taxonomy_version", "") if selected else "",
                        "taxonomy_node": selected.get("taxonomy_node", "") if selected else "",
                        "taxonomy_children": selected.get("taxonomy_children", False) if selected else False,
                    },
                },
            )
        )


@sensitive_post_parameters("query", "state")
@csrf_protect
def workspace(request):
    try:
        policy.enabled()
        action = request.POST.get("action", "")
        if request.method != "POST" or action not in ACTIONS:
            raise InvalidForm("search_form_invalid")
        fields = _form(request, action)
        directory = _provider()
        actor = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        case = Case.objects.filter(public_ref=fields["case_ref"]).first()
        if case is None:
            return denied("search_case_unavailable", 404)
        base = dict(
            case_id=str(case.pk),
            subject_id=actor.subject_id,
            provider=provider,
            synthetic_fixtures_only=True,
        )
        if action in benchmark_views.FIELDS:
            return benchmark_views.handle(request, base, action, fields)
        if action in governance_views.FIELDS:
            return governance_views.handle(request, base, action, fields)
        if action in {"cs_search", "cs_taxonomy_search"}:
            if not fields["page"].isascii() or not fields["page"].isdigit():
                raise InvalidForm("search_page_invalid")
            search = {
                "query": fields["query"],
                "mode": fields["mode"],
                "kind": fields["kind"],
                "page": int(fields["page"]),
                "scope": fields["scope"],
            }
            if action == "cs_taxonomy_search":
                if fields["taxonomy_children"] not in {"0", "1"}:
                    raise InvalidForm("search_taxonomy_children_invalid")
                search.update(
                    taxonomy_version=fields["taxonomy_version"],
                    taxonomy_node=fields["taxonomy_node"],
                    taxonomy_children=fields["taxonomy_children"] == "1",
                )
            return _page(request, base, search=search)
        if action == "cs_source":
            state = _read_state(request, base, fields)
            source_keys = {"binding", "case_ref", "generation_id", "document_id"}
            match_keys = {"query", "mode", "match_index"}
            taxonomy_keys = {"taxonomy_version", "taxonomy_node", "taxonomy_children"}
            if set(state) not in (
                source_keys, source_keys | match_keys, source_keys | match_keys | taxonomy_keys
            ):
                raise InvalidForm("search_result_state_invalid")
            return _page(
                request,
                base,
                selected={
                    key: value for key, value in state.items() if key not in {"binding", "case_ref"}
                },
            )
        if action == "cs_rebuild":
            state = _read_state(request, base, fields)
            if set(state) != {
                "binding",
                "case_ref",
                "revision",
                "evidence_version",
                "generation",
                "request_key",
            }:
                raise InvalidForm("search_rebuild_state_invalid")
            # The command and its response are one unit. A final render denial
            # rolls back the derived generation as well as its document rows.
            with synthetic_queue_atomic():
                services.rebuild(
                    **base,
                    expected_revision=state["revision"],
                    expected_evidence_version=state["evidence_version"],
                    expected_generation=state["generation"],
                    request_key=state["request_key"],
                )
                return _page(request, base, message="اكتملت فهرسة النصوص المتاحة من النسخ الحالية.")
        return _page(request, base)
    except (InvalidForm, SuspiciousOperation, signing.BadSignature, KeyError, TypeError):
        return denied("search_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except cases.CaseConflict:
        return denied("search_not_available_or_stale", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("search_store_unavailable", 503)
