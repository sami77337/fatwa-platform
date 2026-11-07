"""Human-edited training answer drafts pinned to the evidence displayed to the author."""

import re

from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse, HttpResponseRedirect
from django.middleware.csrf import rotate_token
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from apps.fast9_case_source_join.answer_drafts import (
    AUTHOR,
    BODY_LIMIT,
    MAX_DRAFTS,
    TITLE_LIMIT,
    DraftInputError,
)
from apps.fast9_case_source_join.source_journal import (
    JournalError,
    ReviewConflict,
    history_digest,
    read_case_review,
    save_answer_draft,
)

from .reviewer_access import set_role_cookie, signed_in
from .source_review import KINDS
from .source_review_identity import authenticate_fixture_role
from .views import _exact_text, _packet_exact, _source_journal_directory

_TEMPLATE = "editorial_workbench/answer_editor.html"
_FIELDS = {"count", "base_revision", "source_digest", "reply_digest", "title", "body"}
_PIN = re.compile(r"[0-9a-f]{64}")


@sensitive_post_parameters("title", "body", "token")
@require_http_methods(["GET", "HEAD", "POST"])
def answer_editor(request):
    context = {"title_limit": TITLE_LIMIT, "body_limit": BODY_LIMIT}
    authenticated = signed_in(request, "author")
    posted = request.method == "POST"
    if not authenticated and not posted:
        return HttpResponseRedirect(reverse("author_login"))
    status = 200
    resuming = False

    def error(message, code):
        return render(
            request,
            _TEMPLATE,
            {**context, "message": message},
            status=code if authenticated else 403,
        )

    restore = None
    query = request.META.get("QUERY_STRING", "")
    if query:
        match = re.fullmatch(r"from=([1-9][0-9]?)", query)
        if posted or match is None or int(match[1]) > MAX_DRAFTS:
            return error("تعذّر تحديد النسخة المطلوبة. اختر إحدى النسخ من سجلّ المسودة.", 400)
        restore = int(match[1])

    if posted:
        if request.content_type != "application/x-www-form-urlencoded":
            return error("استخدم نموذج كتابة المسودة.", 415)
        try:
            fields = request.POST
            resuming = fields.get("action") == "resume"
            required = _FIELDS | ({"action", "token"} if resuming else set())
            optional = (
                {"csrfmiddlewaretoken"} if resuming else {"csrfmiddlewaretoken", "evidence_seen"}
            )
            if set(fields) - optional != required or any(
                len(fields.getlist(k)) != 1 for k in fields
            ):
                return error("تعذّرت قراءة النموذج. ارجع إلى صفحة كتابة المسودة.", 400)
            # Before reauthentication only echo an admissibly sized form supplied by this POST.
            if not authenticated or resuming:
                if (
                    len(fields["title"]) > TITLE_LIMIT
                    or len(fields["body"]) > BODY_LIMIT
                    or len(fields["title"].encode()) + len(fields["body"].encode()) > 12 * 1024
                ):
                    return error(
                        "تجاوز النص حد الاستئناف. ارجع إلى النموذج وانسخ النص قبل المغادرة.", 400
                    )
            # Keep the human's text even when an optimistic write is refused.
            context.update(
                typed=True, title=_exact_text(fields["title"]), body=_exact_text(fields["body"])
            )
            if (
                not re.fullmatch(r"0|[1-9][0-9]{0,2}", fields["base_revision"])
                or not re.fullmatch(r"[1-9][0-9]{0,2}", fields["count"])
                or int(fields["base_revision"]) > MAX_DRAFTS
                or int(fields["count"]) > 128
                or not _PIN.fullmatch(fields["source_digest"])
                or (fields["reply_digest"] and not _PIN.fullmatch(fields["reply_digest"]))
            ):
                return error("تعذّر تحديد نسخة المسودة أو السؤال. يمكنك نسخ نصك أدناه.", 400)
        except SuspiciousOperation:
            return error("تعذّرت قراءة النموذج المرسل.", 400)
        if not authenticated or resuming:
            if resuming:
                try:
                    authenticate_fixture_role(fields["token"], "author")
                except ValueError:
                    recovery_message = "تعذّر التحقق من رمز المؤلف. بقي نص المحاولة أدناه."
                else:
                    authenticated = True
                    rotate_token(request)
                    recovery_message = ""
            else:
                recovery_message = (
                    "انتهت جلسة المؤلف أو لم تعد صالحة. سجّل الدخول هنا لاستئناف النص الذي كتبته."
                )
            if recovery_message:
                context.update(
                    recovery=True,
                    recovery_pins={
                        k: fields[k]
                        for k in ("count", "base_revision", "source_digest", "reply_digest")
                    },
                )
                return error(recovery_message, 403)
            context["message"] = (
                "استعدت نصّك بعد تسجيل الدخول. راجع الوقائع والنسخة الحالية ثم احفظ عندما تكون جاهزًا."
            )
    directory = _source_journal_directory()
    if directory is None:
        return error("تعذّر فتح مجلد القضية التدريبية.", 503)
    if posted and not resuming:
        try:
            if fields.get("evidence_seen") != "1":
                context["message"] = "اقرأ السؤال والتوضيحات المعروضة ثم أكّد الاطّلاع قبل الحفظ."
                status = 400
            else:
                save_answer_draft(
                    directory,
                    author=AUTHOR,
                    base_revision=int(fields["base_revision"]),
                    count=int(fields["count"]),
                    source_digest=fields["source_digest"],
                    reply_digest=fields["reply_digest"],
                    title=fields["title"],
                    body=fields["body"],
                    evidence_seen=True,
                    synthetic_fixtures_only=True,
                )
                return HttpResponse(
                    status=303, headers={"Location": "/review/author/draft/#draft-status"}
                )
        except DraftInputError as exc:
            context["message"] = (
                "يتجاوز حجم النص سعة النسخة. اختصر العنوان أو المتن ثم أعد الحفظ."
                if str(exc) == "draft_text_too_large"
                else "أدخل عنوانًا ومتنًا للمسودة ضمن الحدود المبينة في النموذج."
            )
            status = 400
        except ReviewConflict:
            context["message"] = (
                "تغيّرت نسخة القضية أو المسودة قبل الحفظ. النص الذي كتبته باقٍ في الحقول أدناه."
            )
            status = 409
        except (JournalError, OSError):
            return error("تعذّر إتمام الحفظ. يمكنك نسخ النص الذي كتبته وإعادة فتح المحرّر.", 503)

    try:
        snapshot = read_case_review(directory, synthetic_fixtures_only=True)
    except (JournalError, OSError):
        return error("تعذّرت قراءة السجل المحفوظ للقضية التدريبية.", 503)
    if not snapshot.events:
        return error("لا يوجد سؤال محفوظ لهذه القضية التدريبية.", 404)

    events = snapshot.events
    last = snapshot.drafts[-1] if snapshot.drafts else None
    head = history_digest(events)
    current = last.revision if last else 0
    if snapshot.draft_notes and snapshot.draft_notes[-1].action == "request":
        note = snapshot.draft_notes[-1]
        context.update(note_text=_packet_exact(note.text), note_revision=note.revision)
    if restore and restore > current:
        return error("لم تُحفظ نسخة بهذا الرقم. اختر إحدى النسخ من سجلّ المسودة.", 404)
    starting = snapshot.drafts[restore - 1] if restore else last
    if not posted:
        context.update(
            title=_exact_text(starting.title if starting else ""),
            body=_exact_text(starting.body if starting else ""),
        )
    context.update(
        case_ready=True,
        base_revision=current,
        count=len(events),
        source_digest=head,
        reply_digest=snapshot.reply_digest,
        last=last,
        restored_from=restore if restore != current else None,
        at_limit=current >= MAX_DRAFTS,
        stale_evidence=bool(
            starting
            and (starting.source_digest, starting.reply_digest) != (head, snapshot.reply_digest)
        ),
        changed_revision=posted and int(fields["base_revision"]) != current,
        changed_evidence=posted
        and (fields["source_digest"], fields["reply_digest"]) != (head, snapshot.reply_digest),
        last_body=_packet_exact(last.body) if last else None,
        source=[
            (
                KINDS[e.kind],
                _packet_exact(e.body_utf8.decode()) if e.body_utf8 is not None else None,
            )
            for e in events
        ],
        thread=[(e.kind, e.actor, _packet_exact(e.text)) for e in snapshot.clarifications],
    )
    response = render(request, _TEMPLATE, context, status=status)
    return set_role_cookie(request, response, "author") if resuming else response
