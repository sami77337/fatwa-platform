"""Authenticated source capture, not automatic case creation or publication."""

from django.db import DatabaseError
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.casework_web.guard import denied, private
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.source_case_intake import services
from apps.source_case_intake.adapters import IntakeError


@csrf_exempt
def callback(request, account_id):
    # Direct invocation without CaseworkGuard admission must fail closed.
    context = getattr(request, "_fatwa_webhook_context", None)
    if context is None:
        return denied("webhook_admission_required", 403)
    if request.path != f"/casework/webhooks/{account_id}/":
        return denied("webhook_account_mismatch", 403)
    if request.method == "GET":
        challenge = getattr(request, "_fatwa_webhook_challenge", None)
        if challenge is None:
            return denied("webhook_verification_required", 403)
        return private(HttpResponse(challenge, content_type="text/plain; charset=utf-8"))
    if request.method != "POST":
        return denied("webhook_method_unavailable", 405)
    raw = getattr(request, "_fatwa_webhook_raw", None)
    if type(raw) is not bytes:
        return denied("webhook_signature_required", 403)
    try:
        # Capture independently commits the literal signed bytes, including
        # unsupported batches. No source is bound to case/evidence here.
        services.capture(raw=raw, context=context, synthetic_fixtures_only=True)
    except (DatabaseError, SyntheticWriteDenied, IntakeError):
        # Provider may retry; never acknowledge a failed durable capture.
        return denied("webhook_storage_unavailable", 503)
    return private(HttpResponse("OK", content_type="text/plain; charset=utf-8"))
