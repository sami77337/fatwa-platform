"""Reviewer feedback tied to a saved training draft, with explicit resolution."""

import re
from datetime import datetime

from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from apps.fast9_case_source_join.answer_drafts import CASE_KEY, MAX_NOTES, DraftInputError
from apps.fast9_case_source_join.source_journal import (
    JournalError,
    ReviewConflict,
    read_case_review,
    history_digest,
    record_draft_note,
)

from .author_access import draft_history_required
from .reviewer_access import signed_in
from .views import _exact_text, _packet_exact, _source_journal_directory

TEMPLATE = "editorial_workbench/draft_notes.html"


@sensitive_post_parameters("text")
@draft_history_required
@require_http_methods(["GET", "HEAD", "POST"])
def draft_notes(request):
    reviewer = signed_in(request)
    author = signed_in(request, "author")
    context = {
        "case_key": CASE_KEY,
        "can_review": reviewer,
        "can_author": author,
    }
    status = 200

    def error(message, code):
        return render(request, TEMPLATE, {**context, "message": message}, status=code)

    if request.META.get("QUERY_STRING"):
        return error("افتح ملاحظات المسودة دون معاملات إضافية.", 400)
    directory = _source_journal_directory()
    if directory is None:
        return error("تعذّر فتح سجل القضية التدريبية.", 503)

    if request.method == "POST":
        if not reviewer and not author:
            return error("سجّل الدخول بالمكتب المختص أولًا.", 403)
        if request.content_type != "application/x-www-form-urlencoded":
            return error("استخدم نموذج الملاحظات المعروض.", 415)
        try:
            fields = request.POST
            if (
                set(fields) - {"csrfmiddlewaretoken"}
                != {"action", "text", "revision", "draft_digest", "note_count"}
                or any(len(fields.getlist(k)) != 1 for k in fields)
                or fields["action"] not in {"request", "close", "withdraw", "submit", "confirm"}
                or not re.fullmatch(r"[1-9][0-9]{0,2}", fields["revision"])
                or not re.fullmatch(r"[0-9a-f]{64}", fields["draft_digest"])
                or not re.fullmatch(r"0|[1-9][0-9]{0,2}", fields["note_count"])
                or (fields["action"] != "request" and fields["text"] != "")
            ):
                return error("تعذّر تحديد الإجراء أو النسخة. افتح أحدث نسخة من الصفحة.", 400)
        except SuspiciousOperation:
            return error("تعذّرت قراءة النموذج.", 400)
        role = "synthetic-mufti-author" if fields["action"] == "submit" else "synthetic-reviewer"
        if (role == "synthetic-mufti-author" and not author) or (
            role == "synthetic-reviewer" and not reviewer
        ):
            return error("لا تملك هذه الهوية صلاحية هذا الإجراء.", 403)
        try:
            record_draft_note(
                directory,
                reviewer=role,
                revision=int(fields["revision"]),
                draft_digest=fields["draft_digest"],
                note_count=int(fields["note_count"]),
                action=fields["action"],
                text=fields["text"],
                synthetic_fixtures_only=True,
            )
        except ReviewConflict:
            status = 409
            context["message"] = (
                "تغيّرت نسخة المسودة أو حالة الملاحظة. راجع النسخة المعروضة قبل تسجيل إجراء جديد."
            )
        except DraftInputError:
            status = 400
            context["message"] = "تحقق من الملاحظة. يقبل الحقل نصًا من حرف واحد إلى 500 حرف."
        except (JournalError, OSError):
            return error("تعذّر حفظ الإجراء في سجل المسودة.", 503)
        else:
            return HttpResponse(status=303, headers={"Location": reverse("draft_notes")})
        if fields["action"] == "request":
            context["text_value"] = _exact_text(fields["text"])

    try:
        snapshot = read_case_review(directory, synthetic_fixtures_only=True)
    except (JournalError, OSError):
        return error("تعذّرت قراءة سجل المسودة وملاحظاته.", 503)
    if not snapshot.events:
        return error("لا توجد قضية تدريب محفوظة في هذا السجل.", 404)
    if snapshot.drafts:
        latest = snapshot.drafts[-1]
        notes = snapshot.draft_notes
        # The journal verifies the alternating request and resolution events.
        history = []
        for original, decision in zip(notes[::2], notes[1::2]):
            history.append(
                {
                    "original": original,
                    "text": _packet_exact(original.text),
                    "decision": decision,
                    "decision_time": datetime.fromisoformat(decision.recorded_at),
                }
            )
        active = notes[-1] if notes and notes[-1].action == "request" else None
        fresh = (
            latest.source_count == len(snapshot.events)
            and latest.source_digest == history_digest(snapshot.events)
            and latest.reply_digest == snapshot.reply_digest
            and not (snapshot.clarifications and snapshot.clarifications[-1].kind == "request")
        )
        last_note = notes[-1] if notes else None
        open_note = bool(last_note and last_note.action == "request")
        pending = bool(
            last_note and last_note.action == "submit" and last_note.revision == latest.revision
        )
        confirmed = bool(
            last_note and last_note.action == "confirm" and last_note.revision == latest.revision
        )
        context.update(
            fresh_evidence=fresh,
            pending_review=pending,
            technical_reviewed=confirmed and fresh,
            can_submit=author and fresh and not open_note and len(notes) < MAX_NOTES
            and not (pending or confirmed),
            can_confirm=reviewer and fresh and pending and len(notes) < MAX_NOTES,
            revision=latest.revision,
            draft_digest=latest.digest,
            title=_packet_exact(latest.title),
            body=_packet_exact(latest.body),
            note_count=len(notes),
            full=len(notes) >= MAX_NOTES,
            active_note=active,
            active_text=_packet_exact(active.text) if active else "",
            newer=bool(active and latest.revision > active.revision),
            history=history[::-1],
        )
    return render(request, TEMPLATE, context, status=status)
