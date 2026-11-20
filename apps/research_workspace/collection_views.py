"""Native private collection forms; signed state binds browser, owner and case."""

from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _provider
from apps.delivery_queue import services as queue
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

from . import collections, views
from .reference_batch import policy_boundary
from .rights import Resource

ACTIONS = {
    "research_collections",
    "research_collection_create",
    "research_collection_open",
    "research_collection_rename",
    "research_collection_archive",
    "research_collection_restore",
    "research_collect",
    "research_save_search",
    "research_collection_add",
    "research_collection_save_search",
    "research_collection_note",
    "research_collection_remove",
    "research_collection_move",
    "research_collection_view",
    "research_collection_compare",
    "research_collection_run_search",
    "research_collection_remove_search",
}
SALT = "research-private-collection.v1"
KEYS = {
    "binding",
    "case_revision",
    "evidence_version",
    "collection_id",
    "collection_revision",
    "item_id",
    "search_id",
}


def _token(binding, result, *, item_id=None, search_id=None):
    return signing.dumps(
        {
            "binding": binding,
            "case_revision": result["revision"],
            "evidence_version": result["evidence_version"],
            "collection_id": result.get("id"),
            "collection_revision": result.get("collection_revision"),
            "item_id": item_id,
            "search_id": search_id,
        },
        salt=SALT,
        compress=True,
    )


def _load(raw, binding):
    if type(raw) is not str or not 1 <= len(raw) <= 3000:
        raise InvalidForm("research_collection_state_invalid")
    try:
        state = signing.loads(raw, salt=SALT, max_age=1800)
        if type(state) is not dict or set(state) != KEYS or state["binding"] != binding:
            raise ValueError()
        cases._mutation_versions(state["case_revision"], state["evidence_version"])
        if state["collection_id"] is not None:
            cases._uuid(state["collection_id"])
            if type(state["collection_revision"]) is not int or state["collection_revision"] < 1:
                raise ValueError()
        return state
    except (ValueError, TypeError, KeyError, signing.BadSignature) as exc:
        raise InvalidForm("research_collection_state_invalid") from exc


def _page(request, *, code=200, **context):
    request._mufti_workspace_error = code >= 400
    get_token(request)
    return private(render(request, "research_workspace/collections.html", context, status=code))


def _states(binding, result):
    result["state"] = _token(binding, result)
    for row in result.get("collections", []):
        row["state"] = _token(binding, row)
    for row in result.get("items", []):
        row["state"] = _token(binding, result, item_id=row["id"])
    for row in result.get("searches", []):
        row["state"] = _token(binding, result, search_id=row["id"])
    return result


@sensitive_post_parameters("state", "source_state", "note", "title")
@csrf_protect
@mutation_service
def workspace(request):
    try:
        collections.enabled()
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS:
            raise InvalidForm("research_collection_form_invalid")
        required = {"action", "case_ref"}
        if action in {"research_collect", "research_save_search"}:
            required.add("source_state")
        elif action != "research_collections":
            required.add("state")
        if action in {
            "research_collection_create",
            "research_collection_rename",
            "research_collection_save_search",
        }:
            required.add("title")
        if action in {"research_collection_add", "research_collection_save_search"}:
            required.add("source_state")
        if action in {"research_collection_add", "research_collection_note"}:
            required.add("note")
        if action == "research_collection_move":
            required.add("direction")
        if action == "research_collection_compare":
            required |= {"first_id", "second_id", "third_id"}
        fields = _form(request, required)
        if request.FILES:
            raise InvalidForm("research_collection_upload_unexpected")
        directory = _provider()
        identity = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        common = dict(
            subject_id=identity.subject_id, provider=provider, synthetic_fixtures_only=True
        )
        selected = next(
            (row for row in cases.list_cases(**common) if row["public_ref"] == fields["case_ref"]),
            None,
        )
        if selected is None:
            return _page(request, code=404, error="المجموعة أو القضية غير متاحة.")
        common["case_id"] = selected["case_id"]
        binding = views._bind(request, identity, provider, fields["case_ref"])
        state = _load(fields["state"], binding) if "state" in fields else None
        source = views._load(fields["source_state"], binding) if "source_state" in fields else None
        pins = dict(
            expected_case_revision=state["case_revision"]
            if state
            else source["revision"]
            if source
            else None,
            expected_evidence_version=state["evidence_version"]
            if state
            else source["evidence_version"]
            if source
            else None,
        )
        if (
            source
            and state
            and (source["revision"], source["evidence_version"])
            != (state["case_revision"], state["evidence_version"])
        ):
            raise cases.CaseConflict("research_collection_case_changed")
        with (
            collections._scope(**common, **pins),
            citations._projection_expiry_guard(),
            policy_boundary(),
        ):
            changes = {}
            chooser = action in {"research_collect", "research_save_search"}
            if chooser or action == "research_collections":
                pending = None
                if action == "research_collect":
                    resource = collections._resource(source["resource"])
                    pending = views.services.open_resource(**common, resource=resource)
                result = _states(binding, collections.list_collections(**common))
                return _page(
                    request,
                    result=result,
                    chooser="item" if action == "research_collect" else "search" if chooser else "",
                    source_state=fields.get("source_state", ""),
                    pending=pending,
                )
            if action == "research_collection_create":
                result = collections.create_collection(**common, **pins, title=fields["title"])
                collection_id = result["id"]
            else:
                collection_id = state["collection_id"]
                if collection_id is None:
                    raise InvalidForm("research_collection_required")
                if action == "research_collection_run_search":
                    filters = collections.saved_search(
                        **common,
                        collection_id=collection_id,
                        search_id=state["search_id"],
                        expected_revision=state["collection_revision"],
                    )
                    result = views._search(common, filters)
                    for row in result["results"]:
                        row["state"] = views._token(binding, result, filters, row["resource"])
                    pagination = []
                    for key, label in (
                        ("previous_page", "الصفحة السابقة"),
                        ("next_page", "الصفحة التالية"),
                    ):
                        if result.get(key):
                            pagination.append(
                                dict(
                                    label=label,
                                    state=views._token(
                                        binding, result, {**filters, "page": result[key]}
                                    ),
                                )
                            )
                    return views._page(
                        request,
                        result=result,
                        filters=filters,
                        pagination=pagination,
                        back_state=views._token(binding, result, filters),
                        notice="أُعيد البحث ضمن حقوقك الحالية؛ لم تتغير عناصر المجموعة المختارة.",
                    )
                changes = {
                    "research_collection_rename": "RENAME",
                    "research_collection_archive": "ARCHIVE",
                    "research_collection_restore": "RESTORE",
                    "research_collection_add": "ADD",
                    "research_collection_note": "NOTE",
                    "research_collection_remove": "REMOVE",
                    "research_collection_move": "MOVE",
                    "research_collection_save_search": "SAVE_SEARCH",
                    "research_collection_remove_search": "REMOVE_SEARCH",
                }
                if action in changes:
                    collections.change_collection(
                        **common,
                        **pins,
                        collection_id=collection_id,
                        expected_revision=state["collection_revision"],
                        action=changes[action],
                        title=fields.get("title", ""),
                        note=fields.get("note", ""),
                        direction=fields.get("direction", ""),
                        item_id=state["item_id"],
                        search_id=state["search_id"],
                        resource=Resource(**source["resource"])
                        if action == "research_collection_add"
                        else None,
                        filters={k: v for k, v in source["filters"].items() if k != "page"}
                        if action == "research_collection_save_search"
                        else None,
                    )
            result = _states(
                binding, collections.read_collection(**common, collection_id=collection_id)
            )
            opened = []
            if action in {"research_collection_view", "research_collection_compare"}:
                ids = (
                    [state["item_id"]]
                    if action == "research_collection_view"
                    else [fields[k] for k in ("first_id", "second_id", "third_id") if fields[k]]
                )
                if action == "research_collection_compare" and len(ids) < 2:
                    raise InvalidForm("research_collection_compare_requires_two")
                opened = collections.open_items(
                    **common,
                    collection_id=collection_id,
                    item_ids=ids,
                    expected_revision=state["collection_revision"],
                )["opened"]
                for item in opened:
                    item["research_state"] = views._token(
                        binding,
                        result,
                        dict(
                            query="",
                            kind="all",
                            edition_id=item["resource"]["edition_id"],
                            printed_part="",
                            printed_page=None,
                        ),
                        item["resource"],
                    )
            return _page(
                request,
                result=result,
                opened=opened,
                notice="حُفظ التغيير في مجموعتك الخاصة."
                if action in changes or action == "research_collection_create"
                else "",
            )
    except IdentityUnavailable:
        return _page(request, code=403, error="يلزم دخول صاحب المجموعة ونطاق القضية الحالي.")
    except (InvalidForm, SuspiciousOperation, TypeError, KeyError):
        return _page(
            request, code=400, error="النموذج أو سياقه غير صالح. افتح مجموعاتك من القضية مجددًا."
        )
    except (cases.CaseConflict, queue.QueueConflict, ValueError):
        return _page(
            request,
            code=409,
            error="تغيرت المجموعة أو القضية، أو تعذر التحقق من حق فتح المادة. أعد فتح المجموعة؛ لم يُستبدل أي أصل.",
        )
    except (DatabaseError, SyntheticWriteDenied):
        return _page(request, code=503, error="المجموعات الخاصة غير متاحة الآن.")
