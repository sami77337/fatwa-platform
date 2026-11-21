"""Native authenticated forms, exact browser-bound state and final render checks."""

import csv
import io
import uuid
from contextlib import nullcontext

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
from apps.casework_web.views import InvalidForm, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.editorial_workbench.reviewer_access import browser_proof
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import formats, policy, roundtrip, services

SALT = "fatwa.material-import.native.v1"
FIELDS = {
    "mi_open": set(),
    "mi_example": set(),
    "mi_batch": {"batch_id"},
    "mi_upload": {"state", "namespace", "provenance", "rights_basis", "synthetic"},
    "mi_map": {"batch_id", "state", *("map_" + field for field in formats.FIELDS)},
    "mi_plan": {"batch_id", "state"},
    "mi_resolve": {"batch_id", "state", "external_id", "choice"},
    "mi_approve": {"batch_id", "state", "plan_id", "note", "verification_note"},
    "mi_reject": {"batch_id", "state", "plan_id", "note", "verification_note"},
    "mi_apply": {"batch_id", "state"},
    "mi_cancel": {"batch_id", "state"},
    "mi_export_open": set(),
    "mi_export_search": {"query", "kind", "page"},
    "mi_export_preview": {"state", "selection"},
    "mi_export": {"state"},
}
ACTIONS = frozenset(FIELDS)
LABELS = {
    "external_id": "هوية السجل في المصدر *",
    "kind": "النوع BOOK / DOCUMENT / IMAGE / AUDIO / VIDEO *",
    "title": "عنوان المادة *",
    "work_title": "اسم العمل أو المصدر *",
    "edition_label": "الطبعة أو النسخة",
    "creator": "صاحب المصدر",
    "description": "الوصف",
    "source_locator": "الموضع الوصفي",
    "provenance": "مصدر البيانات وتوثيقه",
    "rights_basis": "وصف أساس الإتاحة؛ ليس منح صلاحية",
    "language": "اللغة ar / en",
    "source_version": "إصدار المصدر *",
    "recorded_text": "النص المرفق فعلًا",
    "file_member": "مسار الملف المرفق في ZIP",
    "group": "مجموعة التنفيذ الذري",
}


def _form(request, action):
    expected = FIELDS[action] | {"action", "case_ref", "csrfmiddlewaretoken"}
    if set(request.POST) != expected or any(
        not 1
        <= len(request.POST.getlist(key))
        <= (20 if action == "mi_export_preview" and key == "selection" else 1)
        for key in request.POST
    ):
        raise InvalidForm("import_form_fields")
    if action == "mi_upload":
        if (
            request.content_type != "multipart/form-data"
            or set(request.FILES) != {"source_file"}
            or len(request.FILES.getlist("source_file")) != 1
        ):
            raise InvalidForm("import_upload_fields")
    elif request.content_type != "application/x-www-form-urlencoded" or request.FILES:
        raise InvalidForm("import_form_encoding")
    return request.POST


def _binding(request, base, case_ref):
    actor = cases._identity(
        base["provider"], base["subject_id"], Case.objects.get(pk=base["case_id"])
    )
    return browser_proof(
        request,
        SALT,
        "|".join((base["provider"].provider_id, actor.subject_id, actor.auth_epoch, case_ref)),
    )


def _page(request, base, *, batch_id=None, message=""):
    with policy.boundary(**base):
        context = services.list_batches(**base)
        batch = services.read_batch(**base, batch_id=batch_id) if batch_id else None
        get_token(request)
        state = {
            "binding": _binding(request, base, context["case_ref"]),
            "case_ref": context["case_ref"],
            "revision": context["revision"],
            "evidence_version": context["evidence_version"],
            "batch_id": batch["id"] if batch else "",
            "sequence": batch["sequence"] if batch else 0,
            "plan_id": batch["plan"]["id"] if batch and batch["plan"] else "",
            "request_key": str(uuid.uuid4()),
            "targets": {
                row["external_id"]: row["target"] for row in batch["plan"]["report"]["rows"]
            }
            if batch and batch["plan"] and batch["plan"]["report"]
            else {},
        }
        context.update(
            batch=batch, message=message, state=signing.dumps(state, salt=SALT, compress=True)
        )
        if batch:
            context["mapping_fields"] = [
                {"key": key, "label": LABELS[key], "selected": batch["mapping"][key]}
                for key in formats.FIELDS
            ]
        response = private(render(request, "material_import/desk.html", context))
        # Recompute composed projections while still inside both current policy
        # boundaries; rendering cannot race a revocation into a successful page.
        services.list_batches(**base)
        if batch_id:
            services.read_batch(**base, batch_id=batch_id)
        return response


def _state(request, fields, base):
    state = signing.loads(fields["state"], salt=SALT, max_age=900)
    if (
        type(state) is not dict
        or state["case_ref"] != fields["case_ref"]
        or state["binding"] != _binding(request, base, fields["case_ref"])
        or ("batch_id" in fields and state["batch_id"] != fields["batch_id"])
    ):
        raise InvalidForm("import_browser_binding")
    return state


def _export_page(request, base, *, query="", kind="", page=1, preview=None):
    with policy.boundary(**base):
        context = roundtrip.inventory(**base, query=query, kind=kind, page=page)
        if preview:
            preview = roundtrip.revalidate(
                **base,
                selected=preview["selected"],
                prepared_at=preview["prepared_at"],
                expected_sha256=preview["sha256"],
            )
        get_token(request)
        state = {
            "case_ref": context["case_ref"],
            "binding": _binding(request, base, context["case_ref"]),
            "revision": context["revision"],
            "evidence_version": context["evidence_version"],
            "request_key": str(uuid.uuid4()),
            "choices": [row["pin"] for row in context["choices"]],
            "selected": preview["selected"] if preview else [],
            "prepared_at": preview["prepared_at"] if preview else "",
            "sha256": preview["sha256"] if preview else "",
        }
        context.update(
            preview=preview,
            state=signing.dumps(state, salt=SALT, compress=True),
            next_page=page + 1 if context["has_next"] else None,
            previous_page=page - 1 if page > 1 else None,
        )
        response = private(render(request, "material_import/roundtrip.html", context))
        roundtrip.inventory(**base, query=query, kind=kind, page=page)
        if preview:
            roundtrip.revalidate(
                **base,
                selected=preview["selected"],
                prepared_at=preview["prepared_at"],
                expected_sha256=preview["sha256"],
            )
        return response


def _example():
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        [
            "_synthetic",
            "source_key",
            "material_type",
            "heading",
            "work",
            "source_rev",
            "description",
        ]
    )
    writer.writerow(
        [
            "true",
            "sample-book",
            "BOOK",
            "كتاب اصطناعي وصفي",
            "عمل تجريبي",
            "test-v1",
            "لا ملف رقمي ولا متن كتاب؛ بيانات تطوير فقط",
        ]
    )
    return output.getvalue().encode("utf-8-sig")


@sensitive_post_parameters("state", "note", "verification_note", "provenance", "rights_basis")
@csrf_protect
def workspace(request):
    try:
        policy.enabled()
        action = request.POST.get("action", "")
        if request.method != "POST" or action not in ACTIONS or request.GET:
            raise InvalidForm("import_form")
        fields = _form(request, action)
        directory = _provider()
        actor = current_staff(request, directory, case_key=fields["case_ref"])
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        base = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        row = next(
            (row for row in cases.list_cases(**base) if row["public_ref"] == fields["case_ref"]),
            None,
        )
        if row is None:
            return denied("import_case_unavailable", 404)
        base["case_id"] = row["case_id"]
        if action == "mi_open":
            return _page(request, base)
        if action == "mi_batch":
            return _page(request, base, batch_id=fields["batch_id"])
        if action in {"mi_export_open", "mi_export_search"}:
            return _export_page(
                request,
                base,
                **(
                    {"query": fields["query"], "kind": fields["kind"], "page": int(fields["page"])}
                    if action == "mi_export_search"
                    else {}
                ),
            )
        if action == "mi_example":
            with policy.boundary(**base):
                response = HttpResponse(_example(), content_type="text/csv; charset=utf-8")
                response["Content-Disposition"] = (
                    'attachment; filename="synthetic-material-import.csv"'
                )
                return private(response)
        state = _state(request, fields, base)
        changed = dict(
            base,
            expected_revision=state["revision"],
            expected_evidence_version=state["evidence_version"],
        )
        command = dict(request_key=state["request_key"], **changed)
        if action == "mi_export_preview":
            choices = fields.getlist("selection")
            if len(choices) != len(set(choices)) or any(
                not value.isdecimal()
                or str(int(value)) != value
                or int(value) >= len(state["choices"])
                for value in choices
            ):
                raise InvalidForm("roundtrip_selection")
            preview = roundtrip.prepare(
                **changed, selected=[state["choices"][int(value)] for value in choices]
            )
            return _export_page(request, base, preview=preview)
        if action == "mi_export":
            with policy.boundary(**changed, action="EXPORT"):
                result = roundtrip.download(
                    **command,
                    selected=state["selected"],
                    prepared_at=state["prepared_at"],
                    expected_sha256=state["sha256"],
                )
                response = HttpResponse(result["raw"], content_type="application/zip")
                response["Content-Disposition"] = f'attachment; filename="{result["filename"]}"'
                response["X-Material-Roundtrip-SHA256"] = result["sha256"]
                return private(response)
        # Single commands and their rendered receipt commit together. APPLY has
        # intentionally separate group transactions, including external locks;
        # its already committed partial results must survive a later error.
        with nullcontext() if action == "mi_apply" else synthetic_queue_atomic():
            if action == "mi_upload":
                if fields["synthetic"] != "yes":
                    raise InvalidForm("import_synthetic_ack")
                upload = request.FILES["source_file"]
                if upload.size > formats.MAX_BYTES:
                    raise InvalidForm("import_file_size")
                batch = services.stage(
                    raw=upload.read(formats.MAX_BYTES + 1),
                    filename=upload.name,
                    namespace=fields["namespace"],
                    provenance=fields["provenance"],
                    rights_basis=fields["rights_basis"],
                    **command,
                )
            else:
                command.update(batch_id=fields["batch_id"], expected_sequence=state["sequence"])
                if action == "mi_map":
                    batch = services.configure(
                        mapping={key: fields["map_" + key] for key in formats.FIELDS}, **command
                    )
                elif action == "mi_plan":
                    batch = services.prepare_plan(**command)
                elif action == "mi_resolve":
                    batch = services.resolve_conflict(
                        external_id=fields["external_id"],
                        choice=fields["choice"],
                        expected_target=state["targets"][fields["external_id"]],
                        **command,
                    )
                elif action in {"mi_approve", "mi_reject"}:
                    if state["plan_id"] != fields["plan_id"]:
                        raise InvalidForm("import_plan_binding")
                    batch = services.decide(
                        plan_id=fields["plan_id"],
                        verdict="APPROVE" if action == "mi_approve" else "REJECT",
                        note=fields["note"],
                        verification_note=fields["verification_note"],
                        **command,
                    )
                elif action == "mi_apply":
                    batch = services.apply_batch(**command)
                elif action == "mi_cancel":
                    batch = services.cancel(**command)
                else:
                    raise InvalidForm("import_action")
            return _page(request, base, batch_id=batch["id"], message=batch["state_label"])
    except cases.CaseConflict:
        return denied("import_action_not_accepted", 409)
    except (
        InvalidForm,
        formats.ImportInputError,
        signing.BadSignature,
        SuspiciousOperation,
        KeyError,
        TypeError,
        ValueError,
    ):
        return denied("import_form_invalid", 400)
    except IdentityUnavailable:
        return denied("import_access_required", 403)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("import_store_unavailable", 503)
