"""Native forms on the existing staff URL, using its CSRF-bound MUFTI session."""

import json
import secrets
from hashlib import sha256
from hmac import compare_digest

from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.private_media.validation import MAX_BYTES

from . import desk_services as desk_data
from . import services
from .adapters import IntakeError

ACTIONS = frozenset(
    {
        "source_inbox",
        "source_return",
        "source_filter",
        "source_open",
        "source_raw",
        "source_raw_view",
        "source_resolve",
        "source_timeline",
        "source_attach",
        "source_resume",
        "source_note",
        "source_simulate",
    }
)
SALT = "fatwa.source-desk.form.v1"
FILTER_COOKIE = "fatwa_source_filters"


def _listing(request, common, filters=None, **context):
    if filters is None:
        try:
            saved = signing.loads(
                request.get_signed_cookie(FILTER_COOKIE, default="", salt=SALT),
                salt=SALT + ".filters",
                max_age=900,
            )
            if (
                saved["subject"] != common["subject_id"]
                or saved["provider"] != common["provider"].provider_id
            ):
                raise ValueError
            filters = saved["filters"]
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            filters = {}
    result = desk_data.inbox(**common, **filters)
    response = _page(request, inbox=result, **context)
    value = signing.dumps(
        {
            "subject": common["subject_id"],
            "provider": common["provider"].provider_id,
            "filters": filters,
        },
        salt=SALT + ".filters",
    )
    response.set_signed_cookie(
        FILTER_COOKIE,
        value,
        salt=SALT,
        max_age=900,
        httponly=True,
        samesite="Strict",
        path="/casework/staff/",
        secure=False,
    )
    return response


def _page(request, *, status=200, **context):
    request._mufti_workspace_error = status >= 400 or context.get("unbound_source", False)
    get_token(request)
    return private(render(request, "source_case_intake/desk.html", context, status=status))


def _proof(request, common, selected):
    receipt = selected["receipt"]
    value = {
        "receipt": receipt["receipt_id"],
        "sha256": receipt["sha256"],
        "subject": common["subject_id"],
        "provider": common["provider"].provider_id,
        "targets": {
            str(t["id"]): [t["revision"], t["evidence_version"]] for t in selected["candidates"]
        },
        "case_versions": None,
        "notes_version": receipt["notes_version"],
        "operation_nonce": secrets.token_hex(16),
    }
    if receipt["case_id"]:
        case = cases.read_case(case_id=receipt["case_id"], **common)
        value["case_versions"] = [case["revision"], case["evidence_version"]]
    payload = json.dumps(value, sort_keys=True)
    return signing.dumps(
        {"value": value, "browser": browser_proof(request, SALT, payload)}, salt=SALT
    )


def _verify(request, common, fields):
    try:
        saved = signing.loads(fields["proof"], salt=SALT, max_age=900)
        value = saved["value"]
        expected = browser_proof(request, SALT, json.dumps(value, sort_keys=True))
        if (
            value["receipt"] != fields["receipt_id"]
            or value["subject"] != common["subject_id"]
            or value["provider"] != common["provider"].provider_id
            or not compare_digest(saved["browser"], expected)
        ):
            raise ValueError
        selected = desk_data.detail(receipt_id=fields["receipt_id"], **common)
        if selected["receipt"]["sha256"] != value["sha256"]:
            raise ValueError
        if fields.get("case_ref") and fields["case_ref"] != selected["receipt"]["public_ref"]:
            raise ValueError
        return value, selected
    except (signing.BadSignature, ValueError, KeyError, TypeError) as exc:
        raise InvalidForm("source_form_expired_or_changed") from exc


def _detail_page(request, common, receipt_id, notice=""):
    selected = desk_data.detail(receipt_id=receipt_id, **common)
    selected["proof"] = _proof(request, common, selected)
    selected["can_simulate"] = (
        getattr(settings, "FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED", False) is True
        and selected["receipt"]["case_id"] is not None
        and services.REVIEW_SCOPE in common["provider"].resolve(common["subject_id"]).case_keys
    )
    return _page(
        request,
        selected=selected,
        notice=notice,
        unbound_source=selected["receipt"]["case_id"] is None,
    )


@sensitive_post_parameters("token", "note", "proof")
@csrf_protect
def desk(request):
    if getattr(settings, "FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED", False) is not True:
        return _page(request, status=503, error="مكتب المصادر التجريبي مغلق.")
    try:
        directory = _provider()
        actor = current_staff(request, directory)
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        if request.method in ("GET", "HEAD"):
            return _listing(request, common)
        action = request.POST.get("action")
        if request.method != "POST" or action not in ACTIONS:
            raise InvalidForm("source_action_invalid")
        required = {"action"}
        if action == "source_filter":
            required |= {"source", "state", "page"}
            if "query" in request.POST:
                required.add("query")
        elif action == "source_timeline":
            required |= {"case_ref"}
        elif action in {"source_open", "source_raw", "source_raw_view"}:
            required |= {"receipt_id"}
        elif action == "source_resume":
            required |= {"receipt_id", "proof", "confirm"}
        elif action == "source_note":
            required |= {"receipt_id", "proof", "confirm", "kind", "note"}
        elif action == "source_simulate":
            required |= {"receipt_id", "proof", "confirm", "scenario"}
        elif action == "source_resolve":
            required |= {"receipt_id", "proof", "decision", "note", "case_id", "token", "confirm"}
        elif action == "source_attach":
            required |= {"receipt_id", "proof", "source_file_id", "token", "confirm"}
        if (
            action
            in {
                "source_open",
                "source_raw",
                "source_raw_view",
                "source_note",
                "source_attach",
                "source_simulate",
            }
            and "case_ref" in request.POST
        ):
            required.add("case_ref")
        if action == "source_attach":
            if (
                request.content_type != "multipart/form-data"
                or set(request.POST) != required | {"csrfmiddlewaretoken"}
                or any(len(request.POST.getlist(k)) != 1 for k in request.POST)
                or set(request.FILES) != {"attachment"}
                or len(request.FILES.getlist("attachment")) != 1
            ):
                raise InvalidForm("invalid_upload_form")
            fields = request.POST
        else:
            fields = _form(request, required)
            if request.FILES:
                raise InvalidForm("unexpected_files")
        if action in {"source_inbox", "source_filter", "source_return"}:
            filters = (
                None
                if action == "source_return"
                else {}
                if action == "source_inbox"
                else dict(
                    source=fields["source"],
                    state=fields["state"],
                    page=_integer(fields["page"]),
                    query=fields.get("query", ""),
                )
            )
            return _listing(request, common, filters)
        if action == "source_open":
            if (
                fields.get("case_ref")
                and desk_data.detail(receipt_id=fields["receipt_id"], **common)["receipt"][
                    "public_ref"
                ]
                != fields["case_ref"]
            ):
                raise InvalidForm("source_case_context_mismatch")
            return _detail_page(request, common, fields["receipt_id"])
        if action in {"source_raw", "source_raw_view"}:
            if (
                fields.get("case_ref")
                and desk_data.detail(receipt_id=fields["receipt_id"], **common)["receipt"][
                    "public_ref"
                ]
                != fields["case_ref"]
            ):
                raise InvalidForm("source_case_context_mismatch")
            raw = services.staff_raw(
                receipt_id=fields["receipt_id"],
                usage="READ" if action == "source_raw_view" else "EXPORT",
                **common,
            )
            if action == "source_raw_view":
                try:
                    original, encoding = raw.decode("utf-8"), "UTF-8 كما حُفظ"
                except UnicodeDecodeError:
                    original, encoding = (
                        raw.hex(" "),
                        "بايتات ممثلة بالنظام الست عشري؛ النص ليس UTF-8",
                    )
                return _page(
                    request,
                    raw_preview={
                        "text": original,
                        "encoding": encoding,
                        "sha256": sha256(raw).hexdigest(),
                        "size": len(raw),
                        "receipt_id": fields["receipt_id"],
                        "public_ref": fields.get("case_ref", ""),
                    },
                )
            response = HttpResponse(raw, content_type="application/octet-stream")
            response["Content-Disposition"] = 'attachment; filename="source-event.bin"'
            return private(response)
        if action == "source_timeline":
            authorized = cases.list_cases(**common)
            selected_case = next(
                (c for c in authorized if c["public_ref"] == fields["case_ref"]), None
            )
            if selected_case is None:
                raise IdentityUnavailable("source_case_unavailable")
            return _page(
                request, history=desk_data.timeline(case_id=selected_case["case_id"], **common)
            )
        saved, selected = _verify(request, common, fields)
        if fields["confirm"] != "yes":
            raise InvalidForm("human_confirmation_required")
        if action == "source_note":
            desk_data.record_note(
                **common,
                receipt_id=fields["receipt_id"],
                kind=fields["kind"],
                text=fields["note"],
                request_key=saved["operation_nonce"],
                expected_sequence=saved["notes_version"],
            )
            return _detail_page(
                request,
                common,
                fields["receipt_id"],
                "حُفظت ملاحظة المتابعة دون تغيير الأصل أو الوقائع.",
            )
        if action == "source_simulate":
            from .desk_simulator import simulate

            result = simulate(
                **common,
                receipt_id=fields["receipt_id"],
                scenario=fields["scenario"],
                nonce=saved["operation_nonce"],
            )
            return _detail_page(
                request,
                common,
                result["receipt_id"],
                "حُفظ الحدث الاصطناعي المحلي؛ لم يحدث اتصال بمزود.",
            )
        if action == "source_resume":
            desk_data.resume(**common, receipt_id=fields["receipt_id"])
            return _listing(
                request,
                common,
                notice="استؤنفت معالجة الحدث المحفوظ. يبقى الربط الملتبس للمراجعة البشرية.",
            )
        if action == "source_resolve":
            if not selected["can_resolve"]:
                raise IntakeError("correlation_review_required")
            params = {}
            if fields["decision"] == "FOLLOWUP":
                versions = saved["targets"].get(fields["case_id"])
                if versions is None:
                    raise InvalidForm("case_not_offered")
                params = dict(
                    case_id=fields["case_id"],
                    token=fields["token"],
                    expected_revision=versions[0],
                    expected_evidence_version=versions[1],
                )
            elif fields["decision"] != "NEW_CASE" or fields["case_id"] or fields["token"]:
                raise InvalidForm("invalid_split_fields")
            result = services.resolve_review(
                **common,
                receipt_id=fields["receipt_id"],
                action=fields["decision"],
                note=fields["note"],
                expected_notes_version=saved["notes_version"],
                **params,
            )
            # A new case grants no staff scope. Never expose its requester capability.
            return _listing(
                request,
                common,
                resolved=result["public_ref"],
                notice="حُفظ قرار الربط البشري. فتح القضية يتطلب نطاقها المستقل؛ لم يُرسل شيء.",
            )
        if not selected["receipt"]["case_id"] or saved["case_versions"] is None:
            raise IntakeError("declared_bound_attachment_required")
        upload = request.FILES["attachment"]
        if not 1 <= upload.size <= MAX_BYTES:
            raise InvalidForm("file_size_invalid")
        services.attach_fixture(
            receipt_id=fields["receipt_id"],
            source_file_id=fields["source_file_id"],
            token=fields["token"],
            raw=upload.read(MAX_BYTES + 1),
            filename=upload.name,
            media_type=upload.content_type,
            expected_revision=saved["case_versions"][0],
            expected_evidence_version=saved["case_versions"][1],
            staff_subject_id=actor.subject_id,
            staff_provider=provider,
            synthetic_fixtures_only=True,
        )
        return _detail_page(
            request, common, fields["receipt_id"], "حُفظ المرفق وربطه بأصل الرسالة وإصدار الوقائع."
        )
    except IdentityUnavailable:
        return _page(request, status=403, error="يلزم دخول المفتي المخوّل ونطاق المورد الحالي.")
    except (InvalidForm, SuspiciousOperation):
        return _page(
            request, status=400, error="تعذر قبول النموذج. أعد فتح الحدث وراجع الحقول والتأكيد."
        )
    except (IntakeError, cases.CaseConflict):
        return _page(
            request,
            status=409,
            error="لم يُقبل الإجراء: قد تغيرت الصلاحية أو الوقائع أو الربط. أعد فتح الحدث.",
        )
    except (DatabaseError, SyntheticWriteDenied):
        return _page(request, status=503, error="السجل التجريبي غير متاح الآن.")
