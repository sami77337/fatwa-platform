"""One authenticated read receipt on an isolated synthetic development server."""

import re
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe
from django.views.static import serve

from apps.editorial_demo.views import local_only
from apps.fast9_case_source_join.clarifications import (
    MAX_TURNS,
    REPLY_OPTIONS,
    ClarificationInput,
    validate_value,
)
from apps.fast9_case_source_join.draft_source_review import inspect_draft_source
from apps.fast9_case_source_join.source_journal import (
    ReviewConflict,
    acknowledge_review,
    history_digest,
    issue_reply_code,
    read_case_review,
    record_clarification,
    revoke_reply_code,
)

from .reading_diff import reading_diff
from .requester_reply import requester_reply
from .reviewer_access import reviewer_login, reviewer_logout, signed_in
from .source_review import (
    CASE_KEY,
    DRAFT_REVISION,
    KINDS,
    STATUS,
    clarification_rows,
    reading_state,
)
from .source_review_identity import authenticate_fixture_reviewer
from .views import _exact_text, _packet_exact, _source_journal_directory

TEMPLATE = "editorial_workbench/reviewer_desk.html"
DESK_SETTINGS = "apps.editorial_workbench.reviewer_settings"


class DeskGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        local_only(request)
        if settings.SETTINGS_MODULE != DESK_SETTINGS:
            raise Http404
        form_paths = {"/review/", "/review/login/", "/review/logout/", "/review/respond/"}
        methods = ("GET", "HEAD", "POST") if request.path in form_paths else ("GET", "HEAD")
        response = (
            self.get_response(request)
            if request.method in methods
            else HttpResponseNotAllowed(methods)
        )
        response["Cache-Control"] = "no-store"
        response["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        return response


_ACTION_FIELDS = {
    "read": set(),
    "request_clarification": {"prompt"},
    "simulate_reply": {"reply_key"},
    "issue_reply_code": {"grant_revision"},
    "revoke_reply_code": {"grant_revision"},
}


def _form_action(fields):
    action = fields.get("action", "read")
    if action not in _ACTION_FIELDS or any(len(fields.getlist(k)) != 1 for k in fields):
        return None
    names = {"count", "source_digest", "draft_digest"} | _ACTION_FIELDS[action]
    if "token" in fields:
        names.add("token")
    actual = set(fields) - {"csrfmiddlewaretoken", "action"}
    if action == "read" and "resume_prompt" in actual:
        names.add("resume_prompt")
    if action == "simulate_reply" and "reply_text" in actual:
        names.add("reply_text")
    # Forms opened on the previous version can confirm only a case without a new reply.
    if action != "read" or {"thread_digest", "reply_digest"} & actual:
        names |= {"thread_digest", "reply_digest"}
    if (
        actual != names
        or not re.fullmatch(r"[1-9][0-9]{0,2}", fields["count"])
        or int(fields["count"]) > 128
    ):
        return None
    if not all(re.fullmatch(r"[0-9a-f]{64}", fields[k]) for k in ("source_digest", "draft_digest")):
        return None
    if any(
        value and not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in (fields.get("reply_digest"), fields.get("thread_digest"))
    ):
        return None
    if "grant_revision" in names and not re.fullmatch(
        r"0|[1-9][0-9]{0,17}", fields["grant_revision"]
    ):
        return None
    return action


@sensitive_post_parameters("token", "prompt", "reply_text", "resume_prompt")
@require_http_methods(["GET", "HEAD", "POST"])
def reviewer_desk(request):
    if not signed_in(request):
        if request.method in {"GET", "HEAD"}:
            return HttpResponseRedirect(reverse("reviewer_login"))
        return render(
            request,
            "editorial_workbench/reviewer_login.html",
            {"message": "سجّل الدخول برمز المراجع أولًا."},
            status=403,
        )
    directory = _source_journal_directory()

    def failure(message, status):
        return render(request, TEMPLATE, {"message": message}, status=status)

    if request.META.get("QUERY_STRING"):
        return failure("افتح رابط مكتب المراجعة دون معاملات إضافية.", 400)
    if directory is None:
        return failure("تعذّر فتح مجلد سجل التدريب.", 503)

    status = 200
    issued = None
    message = ""
    prompt_value = ""
    reply_value = ""
    reply_target = None
    if request.method == "POST":
        if request.content_type != "application/x-www-form-urlencoded":
            return failure("استخدم نموذج تسجيل القراءة المعروض في المكتب.", 415)
        try:
            fields = request.POST
            action = _form_action(fields)
            if action is None:
                return failure("تعذّر تحديد الإجراء أو نسخة القضية من النموذج.", 400)
        except SuspiciousOperation:
            return failure("تعذّرت قراءة النموذج.", 400)
        try:
            reviewer = (
                authenticate_fixture_reviewer(fields["token"])
                if "token" in fields
                else "synthetic-reviewer"
            )
        except ValueError:
            return failure("تعذّر التحقق من رمز المراجع. ارجع وأعد إدخال الرمز.", 403)
        version = {
            "reviewer": reviewer,
            "count": int(fields["count"]),
            "source_digest": fields["source_digest"],
            "draft_digest": fields["draft_digest"],
            "synthetic_fixtures_only": True,
        }
        prompt_value = fields.get("prompt", fields.get("resume_prompt", ""))
        reply_value = fields.get("reply_text", "")
        try:
            if action == "read":
                if prompt_value:
                    validate_value("request", prompt_value)
                acknowledge_review(
                    directory, **version, reply_digest=fields.get("reply_digest", "")
                )
            elif action in {"issue_reply_code", "revoke_reply_code"}:
                grant = {
                    **version,
                    "thread_digest": fields["thread_digest"],
                    "grant_revision": int(fields["grant_revision"]),
                }
                if action == "issue_reply_code":
                    issued = issue_reply_code(directory, **grant)
                else:
                    revoke_reply_code(directory, **grant)
            else:
                kind, value = "request", prompt_value
                if action == "simulate_reply":
                    reply_target = fields["thread_digest"]
                    key = fields["reply_key"]
                    if bool(key) == bool(reply_value) or (key and key not in REPLY_OPTIONS):
                        raise ClarificationInput("choose_one_reply")
                    kind, value = "reply", REPLY_OPTIONS[key] if key else reply_value
                record_clarification(
                    directory,
                    **version,
                    thread_digest=fields["thread_digest"],
                    kind=kind,
                    value=value,
                )
        except ClarificationInput:
            status = 400
            message = (
                "اكتب نص استيضاح تدريبي من حرف واحد إلى 500 حرف دون محارف تحكّم."
                if action != "simulate_reply"
                else "اكتب ردًّا تدريبيًا حتى 500 حرف أو اختر مثالًا واحدًا من القائمة."
            )
        except ReviewConflict:
            status = 409
            message = "تعذّر حفظ الإجراء على النسخة السابقة. راجع السؤال والردود وحالة الطلب في النسخة المعروضة."
        except (ValueError, OSError):
            return failure("تعذّر التحقق من سجل القضية أو حفظ الإجراء.", 503)
        else:
            if issued:
                message = "أُصدر رمز لهذا الاستيضاح. انسخه الآن لفتحه من صفحة صاحب السؤال."
            elif action == "read" and prompt_value:
                # Only an explicit later request submits the retained text.
                message = "سُجّلت قراءتك. احتفظ النموذج بنص طلبك لتراجعه قبل حفظه."
            else:
                location = reverse("reviewer_desk")
                if action in {"request_clarification", "revoke_reply_code"}:
                    location += "#clarification-thread"
                return HttpResponse(status=303, headers={"Location": location})

    try:
        snapshot = read_case_review(directory, synthetic_fixtures_only=True)
        events, receipt = snapshot.events, snapshot.receipt
        if not events:
            return failure("لا توجد أحداث محفوظة لهذه القضية في سجل التدريب.", 404)
        observation = inspect_draft_source(
            CASE_KEY, DRAFT_REVISION, events, synthetic_fixtures_only=True
        )
    except (ValueError, OSError):
        return failure("تعذّرت قراءة سجل السؤال والقراءات المسجّلة.", 503)

    if issued and (
        snapshot.grant_revision != int(fields["grant_revision"]) + 1
        or snapshot.grant_expires_at is None
    ):
        issued = None
        status = 409
        message = "تغيّرت حالة رمز الردّ أثناء فتح الصفحة. راجع حالة الاستيضاح الحالية."

    digest = history_digest(events)
    reviewed_count = receipt.count if receipt else 0
    state = reading_state(
        receipt, len(events), observation.draft_revision_sha256, snapshot.reply_digest
    )
    thread = clarification_rows(snapshot)
    waiting = bool(thread and thread[-1]["kind"] == "request")

    difference = reading_diff(events, reviewed_count)
    if difference:
        difference["segments"] = [
            {"kind": part["kind"], "text": _exact_text(part["text"])}
            for part in difference["segments"]
        ]
    timeline = [
        {
            "number": i,
            "label": KINDS[e.kind],
            "is_new": i > reviewed_count,
            "body": _packet_exact(e.body_utf8.decode()) if e.body_utf8 is not None else None,
        }
        for i, e in enumerate(events, 1)
    ]
    return render(
        request,
        TEMPLATE,
        {
            "case_key": CASE_KEY,
            "revision": DRAFT_REVISION,
            "current_count": len(events),
            "source_digest": digest,
            "draft_digest": observation.draft_revision_sha256,
            "source_status": STATUS[observation.status],
            "original": timeline[0]["body"],
            "latest": timeline[-1]["body"],
            "events": timeline,
            "reviewed_count": reviewed_count,
            "review_state": state,
            "reading_diff": difference,
            "recorded_at": datetime.fromisoformat(receipt.recorded_at) if receipt else None,
            "message": message,
            "can_ack": True,
            "thread": thread,
            "thread_digest": snapshot.thread_digest,
            "reply_digest": snapshot.reply_digest,
            "waiting": waiting,
            "reply_portal_url": reverse("requester_reply"),
            "can_issue_code": waiting and state == "current",
            "grant_active": snapshot.grant_expires_at is not None,
            "grant_revision": snapshot.grant_revision,
            "grant_expires_at": snapshot.grant_expires_at,
            "issued_code": issued.code if issued else "",
            "has_new_reply": any(e["unread"] for e in thread),
            "can_request": state == "current" and not waiting and len(thread) < MAX_TURNS,
            "thread_full": len(thread) == MAX_TURNS,
            "can_reply": waiting,
            "reply_options": REPLY_OPTIONS,
            "prompt_value": prompt_value,
            "reply_value": reply_value if reply_target == snapshot.thread_digest else "",
            "detached_reply": reply_value if reply_target != snapshot.thread_digest else "",
        },
        status=status,
    )


urlpatterns = [
    path("review/", reviewer_desk, name="reviewer_desk"),
    path("review/login/", reviewer_login, name="reviewer_login"),
    path("review/logout/", reviewer_logout, name="reviewer_logout"),
    path("review/respond/", requester_reply, name="requester_reply"),
    path(
        "dev/editorial-workbench/style.css",
        require_safe(serve),
        {"path": "workbench.css", "document_root": Path(__file__).parent},
    ),
]
