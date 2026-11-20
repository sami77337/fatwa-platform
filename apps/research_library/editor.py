"""Native case-scoped library forms and real current-authority file responses."""

import uuid

from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _integer, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

from . import services
from .models import LibraryVersion

ACTIONS = {"rl_open", "rl_search", "rl_item", "rl_edit", "rl_save", "rl_decide"}
LABELS = {
    "BOOK": "كتاب ونسخة",
    "DOCUMENT": "وثيقة",
    "IMAGE": "صورة",
    "AUDIO": "تسجيل صوتي",
    "VIDEO": "تسجيل مرئي",
}
USE_LABELS = {
    "READ": "قراءة الملف داخل مساحة العمل",
    "DOWNLOAD": "تنزيل الملف",
    "CITE": "الاستشهاد بالنسخة",
    "EXPORT": "التصدير المحدد",
    "OFFLINE": "حفظ نسخة للقراءة دون اتصال",
    "PUBLIC_METADATA": "إتاحة البيانات الوصفية للقارئ",
    "PUBLIC_CONTENT": "إتاحة النص والملف للقارئ",
}
ACTION_LABELS = {
    "REVIEW": "تسجيل مراجعة المصدر والنسبة",
    "APPROVE": "اعتماد الاستخدامات المحددة",
    "RELEASE": "إتاحة النسخة للقارئ لمدة محددة",
    "REVOKE": "سحب الإتاحة العامة",
    "WITHDRAW": "سحب استخدام هذه النسخة",
}
FIELD_LABELS = {
    "title": "عنوان المادة",
    "work_title": "اسم العمل أو المصدر",
    "edition_label": "الطبعة أو النسخة المعينة",
    "creator": "اسم صاحب المادة كما ورد في المصدر",
    "description": "وصف المادة",
    "source_locator": "موضع وصفي موثق أو مرجع المصدر",
    "provenance": "مصدر الإدخال وما يمكن التحقق منه",
    "rights_basis": "مرجع الحق أو الإذن المقدم للمراجعة",
    "source_version": "معرّف النسخة لدى المصدر",
    "recorded_text": "نص منقول متاح، اختياري",
}


def _zero(value):
    return 0 if value == "0" else _integer(value)


def _fields(request, action):
    required = {"action", "case_ref"}
    repeated = set()
    optional = set()
    if action == "rl_search":
        required |= {"query", "kind", "page"}
    if action in {"rl_item", "rl_edit"}:
        required.add("version_id")
    if action == "rl_save":
        # Browsers submit an untouched file input with filename="". Django
        # represents that part as one empty POST value instead of a file.
        optional.add("source_file")
        required |= {
            *services.FIELDS,
            "kind",
            "language",
            "namespace",
            "external_id",
            "expected_version",
            "revision",
            "evidence_version",
            "request_key",
        }
    if action == "rl_decide":
        required |= {
            "version_id",
            "command",
            "note",
            "expected_actions",
            "revision",
            "evidence_version",
            "request_key",
            "minutes",
            "confirmed",
        }
        repeated.add("uses")
    if (
        request.method != "POST"
        or request.GET
        or action not in ACTIONS
        or request.content_type
        not in (
            {"multipart/form-data"}
            if action == "rl_save"
            else {"application/x-www-form-urlencoded"}
        )
        or not required | {"csrfmiddlewaretoken"}
        <= set(request.POST)
        <= required | repeated | optional | {"csrfmiddlewaretoken"}
        or any(len(values) != 1 for key, values in request.POST.lists() if key not in repeated)
        or len(request.POST.getlist("uses")) > 7
        or (action != "rl_save" and request.FILES)
        or set(request.FILES) - {"source_file"}
        or any(len(request.FILES.getlist(key)) != 1 for key in request.FILES)
        or (
            "source_file" in request.POST
            and (request.POST.getlist("source_file") != [""] or "source_file" in request.FILES)
        )
    ):
        raise InvalidForm("library_form_invalid")
    return request.POST


def _common(request, case_ref):
    directory = _provider()
    actor = current_staff(request, directory, case_key=case_ref)
    provider = RequestDirectory(directory, actor, authenticated_provider_id=directory.provider_id)
    case = Case.objects.filter(public_ref=case_ref).first()
    if case is None:
        raise cases.CaseConflict("library_case_unavailable")
    return dict(
        case_id=str(case.pk),
        subject_id=actor.subject_id,
        provider=provider,
        synthetic_fixtures_only=True,
    )


def _options(record, common):
    permitted, uses = [], []
    with services.staff_boundary(**common) as (case, actor):
        row = services._row(case, record["version_id"])
        services._watch(row, file=True)
        names = {item["action"] for item in record["history"]}
        proposed = []
        if not names and (row.provider_id, row.subject_id) != (
            common["provider"].provider_id,
            actor.subject_id,
        ):
            proposed.append("REVIEW")
        if names == {"REVIEW"}:
            review = row.decisions.get(action="REVIEW")
            if (common["provider"].provider_id, actor.subject_id) not in {
                (row.provider_id, row.subject_id),
                (review.provider_id, review.subject_id),
            }:
                proposed.append("APPROVE")
        if names == {"REVIEW", "APPROVE"}:
            proposed.append("RELEASE")
        if "RELEASE" in names and not names & {"REVOKE", "WITHDRAW"}:
            proposed.append("REVOKE")
        if "WITHDRAW" not in names:
            proposed.append("WITHDRAW")
        for action in [*proposed, "READ", "DOWNLOAD", "EXPORT", "OFFLINE"]:
            if action in services.USES:
                try:
                    services._approval(row, action)
                except cases.CaseConflict:
                    continue
                if not row.blob_id and action in {"READ", "DOWNLOAD"}:
                    continue
            values = dict(
                provider_id=common["provider"].provider_id,
                subject_id=actor.subject_id,
                auth_epoch=actor.auth_epoch,
                case_ref=case.public_ref,
                action=action,
                **services._fields(row),
            )
            try:
                services._permit_raw(services.policy_snapshot()[0], values)
            except cases.CaseConflict as exc:
                if str(exc) == "library_action_denied":
                    continue
                raise
            for scope in services._SCOPES.get():
                scope.permissions.append(values)
            if action in proposed:
                permitted.append((action, ACTION_LABELS[action]))
            else:
                uses.append(action)
    return permitted, uses


@mutation_service
def _page(request, common, *, selected_id=None, edit=False, message="", query="", kind="", page=1):
    with synthetic_queue_atomic():
        before = services.head_fingerprint(common["case_id"])
        with services.staff_boundary(**common):
            result = services.browse(**common, query=query, kind=kind, page=page)
            selected = (
                services.read_material(**common, version_id=selected_id) if selected_id else None
            )
            if selected:
                selected["options"], selected["allowed_uses"] = _options(selected, common)
                selected["versions"] = [
                    services.read_material(**common, version_id=pk)
                    for pk in LibraryVersion.objects.filter(item_id=selected["item_id"])
                    .order_by("-number")
                    .values_list("pk", flat=True)
                ]
            edit_payload = selected["payload"] if edit and selected else {}
            fields = [
                {
                    "name": key,
                    "label": FIELD_LABELS[key],
                    "maximum": maximum,
                    "required": key
                    in {"title", "work_title", "source_version", "provenance", "rights_basis"},
                    "value": edit_payload.get(key, ""),
                    "multiline": key
                    in {"description", "provenance", "rights_basis", "recorded_text"},
                }
                for key, maximum in services.FIELDS.items()
            ]
            response = private(
                render(
                    request,
                    "research_library/desk.html",
                    {
                        "result": result,
                        "selected": selected,
                        "editing": edit,
                        "fields": fields,
                        "kinds": LABELS,
                        "use_labels": USE_LABELS,
                        "key": str(uuid.uuid4()),
                        "message": message,
                        "edit_kind": edit_payload.get("kind", "BOOK"),
                        "edit_language": edit_payload.get("language", "ar"),
                    },
                )
            )
        if services.head_fingerprint(common["case_id"]) != before:
            raise cases.CaseConflict("library_render_head_changed")
        return response


@sensitive_post_parameters()
@csrf_protect
def workspace(request):
    try:
        services.enabled()
        action = request.POST.get("action", "")
        fields = _fields(request, action)
        common = _common(request, fields["case_ref"])
        file = request.FILES.get("source_file") if action == "rl_save" else None
        raw = file.read(192001) if file else b""
        with services.material_bindings([raw] if raw else []), synthetic_queue_atomic():
            if action == "rl_search":
                return _page(
                    request,
                    common,
                    query=fields["query"],
                    kind=fields["kind"],
                    page=_integer(fields["page"]),
                )
            if action in {"rl_item", "rl_edit"}:
                return _page(
                    request, common, selected_id=fields["version_id"], edit=action == "rl_edit"
                )
            if action == "rl_save":
                payload = {key: fields[key] for key in services.FIELDS}
                payload.update(kind=fields["kind"], language=fields["language"], synthetic=True)
                record = services.write_material(
                    **common,
                    namespace=fields["namespace"],
                    external_id=fields["external_id"],
                    payload=payload,
                    file_bytes=raw,
                    filename=file.name if file else "",
                    media_type=file.content_type if file else "",
                    expected_version=_zero(fields["expected_version"]),
                    request_key=fields["request_key"],
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                )
                return _page(
                    request,
                    common,
                    selected_id=record["version_id"],
                    message="حُفظت نسخة مستقلة للمراجعة. لم تمنح حقوق قراءة أو نشر تلقائيًا.",
                )
            if action == "rl_decide":
                record = services.decide(
                    **common,
                    version_id=fields["version_id"],
                    action=fields["command"],
                    note=fields["note"],
                    expected_actions=_zero(fields["expected_actions"]),
                    request_key=fields["request_key"],
                    uses=fields.getlist("uses"),
                    minutes=_zero(fields["minutes"]),
                    confirmed=fields["confirmed"] == "yes",
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                )
                return _page(
                    request,
                    common,
                    selected_id=record["version_id"],
                    message="حُفظ القرار على هذه النسخة المحددة.",
                )
            return _page(request, common)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError) as exc:
        if isinstance(exc, cases.CaseConflict):
            return denied("library_action_unavailable", 409)
        return denied("library_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("library_store_unavailable", 503)


@mutation_service
def file(request, version_id, download=False):
    try:
        services.enabled()
        if request.method not in {"GET", "HEAD"} or request.GET:
            raise InvalidForm("library_file_form_invalid")
        # The opaque version is only a locator, never a capability.
        row = LibraryVersion.objects.filter(pk=version_id).select_related("item__case").first()
        if row is None:
            return denied("library_file_unavailable", 404)
        common = _common(request, row.item.case.public_ref)
        usage = "DOWNLOAD" if download else "READ"
        with services.staff_boundary(**common):
            result = services.file_content(**common, version_id=version_id, usage=usage)
            response = HttpResponse(result["raw"], content_type=result["media_type"])
            response["Content-Disposition"] = (
                "attachment" if usage == "DOWNLOAD" else "inline"
            ) + f'; filename="{result["filename"]}"'
            response["Content-Security-Policy"] = (
                "sandbox; default-src 'none'; frame-ancestors 'none'"
            )
            response["X-Content-SHA256"] = result["sha256"]
            return private(response, head=request.method == "HEAD")
    except IdentityUnavailable:
        return denied("library_file_unavailable", 403)
    except cases.CaseConflict:
        return denied("library_file_unavailable", 404)
    except (InvalidForm, SuspiciousOperation):
        return denied("library_file_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("library_store_unavailable", 503)
