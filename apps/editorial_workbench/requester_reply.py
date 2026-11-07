"""Restricted reply form for one locally issued synthetic clarification code."""

from datetime import datetime
from hmac import compare_digest

from django.core.exceptions import SuspiciousOperation
from django.shortcuts import render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from apps.fast9_case_source_join.clarifications import ClarificationInput
from apps.fast9_case_source_join.source_journal import (
    JournalError,
    ReplyCodeUnavailable,
    open_reply_code,
    submit_requester_reply,
)

from .reviewer_access import browser_proof
from .views import _packet_exact, _source_journal_directory


@sensitive_post_parameters("code", "text", "form_proof")
@require_http_methods(["GET", "HEAD", "POST"])
def requester_reply(request):
    def page(phase="enter", *, status=200, **context):
        return render(
            request,
            "editorial_workbench/requester_reply.html",
            {"phase": phase, **context},
            status=status,
        )

    if request.META.get("QUERY_STRING"):
        return page(status=400, message="افتح صفحة الردّ وأدخل الرمز في الحقل المخصص.")
    if request.method != "POST":
        return page()
    if request.content_type != "application/x-www-form-urlencoded":
        return page(status=415, message="استخدم نموذج الردّ المعروض.")
    try:
        fields = request.POST
        action = fields.get("action")
        expected = {"action", "code"} | ({"form_proof", "text"} if action == "reply" else set())
        if (
            action not in {"open", "reply"}
            or set(fields) - {"csrfmiddlewaretoken"} != expected
            or any(len(fields.getlist(k)) != 1 for k in fields)
        ):
            return page(status=400, message="تعذّرت قراءة النموذج.")
    except SuspiciousOperation:
        return page(status=400, message="تعذّرت قراءة النموذج.")

    directory = _source_journal_directory()
    if directory is None:
        return page(status=503, message="صفحة الردّ غير متاحة الآن.")
    code = fields["code"]
    text = ""
    message = ""
    status = 200
    proof = browser_proof(request, "training.requester.compose", code)
    try:
        if action == "reply":
            if not compare_digest(fields["form_proof"].encode(), proof.encode()):
                raise ReplyCodeUnavailable("unavailable")
            text = fields["text"]
            try:
                turn = submit_requester_reply(directory, code, text, synthetic_fixtures_only=True)
            except ClarificationInput:
                status = 400
                message = "اكتب ردًّا من حرف واحد إلى 500 حرف دون محارف تحكّم."
            else:
                return page(
                    "sent",
                    reply_reference=turn.reply_reference,
                    sent_at=datetime.fromisoformat(turn.recorded_at),
                    reply_exact=_packet_exact(turn.text),
                )
        prompt = open_reply_code(directory, code, synthetic_fixtures_only=True)
    except ReplyCodeUnavailable:
        # Return only the text supplied in this POST, never details from the journal.
        return page(
            status=403,
            message="تعذّر فتح الطلب بهذا الرمز. اطلب رمزًا صالحًا من المراجع.",
            unsent_exact=_packet_exact(text) if text and len(text) <= 500 else None,
        )
    except (JournalError, OSError):
        return page(status=503, message="تعذّرت قراءة الطلب أو حفظ الردّ. حاول لاحقًا.")
    return page(
        "compose",
        status=status,
        message=message,
        code=code,
        form_proof=proof,
        prompt_exact=_packet_exact(prompt.prompt),
        source_exact=_packet_exact(prompt.question) if prompt.question is not None else None,
        text_value=text,
        expires_at=prompt.expires_at,
    )
