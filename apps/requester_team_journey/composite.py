"""Native staff preparation of signed multipart plans; no transport or signer."""

import json
from hmac import compare_digest

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _provider
from apps.composite_delivery import services
from apps.delivery_planner.planner import InvalidPlan
from apps.delivery_queue import services as queue
from apps.delivery_queue.author_handoff import InvalidSignedResponse, decode_signed_response
from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

ACTIONS = {"composite_open", "composite_export", "composite_stage", "composite_reconcile"}


@sensitive_post_parameters("response_json")
@csrf_protect
def desk(request):
    try:
        services._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("composite_form_invalid")
        action = request.POST["action"]
        required = {"action", "case_ref"}
        if action == "composite_stage":
            required |= {"response_json", "confirm"}
        elif action == "composite_reconcile":
            required |= {"plan_sha256", "confirm"}
        fields = _form(request, required)
        if request.FILES:
            raise InvalidForm("composite_form_invalid")
        directory = _provider()
        identity = current_staff(request, directory)
        provider = RequestDirectory(
            directory, identity, authenticated_provider_id=directory.provider_id
        )
        common = {
            "subject_id": identity.subject_id,
            "provider": provider,
            "synthetic_fixtures_only": True,
        }
        selected = next(
            (c for c in cases.list_cases(**common) if c["public_ref"] == fields["case_ref"]), None
        )
        if selected is None:
            return denied("composite_unavailable", 404)
        common["case_id"] = selected["case_id"]
        prepared = services.prepare_composite_delivery(**common)
        notice = ""
        if action == "composite_export":
            response = HttpResponse(
                json.dumps(prepared, ensure_ascii=False, indent=2),
                content_type="application/json; charset=utf-8",
            )
            response["Content-Disposition"] = 'attachment; filename="synthetic-composite-plan.json"'
            return private(response)
        if action in {"composite_stage", "composite_reconcile"}:
            if fields["confirm"] != "yes":
                raise InvalidForm("confirmation_required")
            if not isinstance(
                getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None),
                Ed25519ProviderEventVerifier,
            ):
                raise cases.CaseConflict("composite_provider_verifier_unavailable")
            if action == "composite_stage":
                digest, receipt = decode_signed_response(fields["response_json"])
                if not compare_digest(digest, prepared["plan_sha256"]):
                    raise cases.CaseConflict("composite_plan_changed")
                services.stage_composite_delivery(
                    **common,
                    receipt=receipt,
                    verify_receipt=getattr(settings, "FATWA_CASE_DELIVERY_APPROVAL_VERIFIER", None),
                )
                notice = "سُجلت خطة الأجزاء المعتمدة في الطابور الحالي. لم يحدث إرسال."
            else:
                if not compare_digest(fields["plan_sha256"], prepared["plan_sha256"]):
                    raise cases.CaseConflict("composite_plan_changed")
                result = services.reconcile_composite_timeouts(**common)
                notice = f"سُجلت {result['unresolved_parts']} محاولة منتهية كغير محسومة. لا إعادة إرسال تلقائية."
        status = None
        try:
            status = services.composite_status(
                **common,
                verifier=getattr(settings, "FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER", None),
            )
        except cases.CaseConflict as exc:
            if str(exc) != "composite_delivery_not_staged":
                raise
        get_token(request)
        return private(
            render(
                request,
                "composite_delivery/desk.html",
                {
                    "selected": selected,
                    "prepared": prepared,
                    "status": status,
                    "notice": notice,
                },
            )
        )
    except (InvalidForm, InvalidSignedResponse, SuspiciousOperation):
        return denied("composite_form_invalid", 400)
    except IdentityUnavailable:
        return denied("staff_identity_required", 403)
    except (cases.CaseConflict, queue.QueueConflict, InvalidPlan):
        return denied("composite_context_unavailable", 409)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("composite_store_unavailable", 503)
