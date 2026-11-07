"""Browse saved human draft versions and their supporting case evidence."""

import re
from datetime import datetime

from django.core.exceptions import TooManyFieldsSent
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.fast9_case_source_join.source_journal import JournalError, read_case_review

from .author_access import draft_history_required
from .reading_diff import word_segments
from .reviewer_access import signed_in
from .source_review import CASE_KEY
from .views import _exact_text, _packet_exact, _source_journal_directory

TEMPLATE = "editorial_workbench/answer_history.html"


def _text_pair(label, left, right):
    changed = left != right
    # Each side retains its exact text, even when the comparison budget is exceeded.
    segments = word_segments(left, right) if changed else None
    return {
        "label": label,
        "before": _packet_exact(left),
        "after": _packet_exact(right),
        "changed": changed,
        "segments": [{"kind": s["kind"], "text": _exact_text(s["text"])} for s in segments or ()],
    }


def _evidence(snapshot, draft):
    source = snapshot.events[draft.source_count - 1].body_utf8
    replies = []
    if draft.reply_digest:
        for turn in snapshot.clarifications:
            replies.append({"is_request": turn.kind == "request", "text": _packet_exact(turn.text)})
            if turn.digest == draft.reply_digest:
                break  # The reader of the journal verified this version points to a reply.
    return {
        "revision": draft.revision,
        "source_count": draft.source_count,
        "question": _packet_exact(source.decode()) if source is not None else None,
        "replies": replies,
    }


@draft_history_required
@require_safe
def answer_history(request):
    def error(message, status):
        return render(request, TEMPLATE, {"message": message}, status=status)

    try:
        params = request.GET
        if set(params) - {"before", "after", "q"} or any(
            len(params.getlist(k)) != 1 for k in params
        ):
            return error("تعذّرت قراءة اختيار النسخ. افتح سجل المسودة واختر من القائمة.", 400)
        selected = {k: params[k] for k in ("before", "after") if k in params}
        if any(not re.fullmatch(r"[1-9][0-9]{0,2}", v) for v in selected.values()):
            return error("اختر رقم نسخة محفوظة.", 400)
        query = params.get("q", "")
        if len(query) > 80 or any(ord(c) < 32 for c in query):
            return error("اكتب عبارة بحث لا تتجاوز 80 حرفًا في سطر واحد.", 400)
    except TooManyFieldsSent:
        return error("تعذّرت قراءة معايير البحث.", 400)
    directory = _source_journal_directory()
    if directory is None:
        return error("تعذّر فتح سجل القضية.", 503)
    try:
        state = read_case_review(directory, synthetic_fixtures_only=True)
    except (JournalError, OSError):
        return error("تعذّرت قراءة نسخ المسودة المحفوظة.", 503)
    if not state.events:
        return error("لا توجد قضية تدريب محفوظة في هذا السجل.", 404)
    rows = state.drafts
    versions = {r.revision: r for r in rows}
    if any(int(v) not in versions for v in selected.values()):
        return error("لم يُعثر على رقم النسخة المطلوب لهذه القضية.", 404)
    context = {
        "case_key": CASE_KEY,
        "versions": rows,
        "query": query,
        "can_author": signed_in(request, "author"),
    }
    if not rows:
        return render(request, TEMPLATE, context)

    after = versions[int(selected["after"])] if "after" in selected else rows[-1]
    before = (
        versions[int(selected["before"])]
        if "before" in selected
        else next((r for r in reversed(rows) if r.revision < after.revision), after)
    )
    needle = query.strip().casefold()
    history = []
    for index, row in enumerate(rows):
        previous = rows[index - 1] if index else None
        if needle and needle not in row.title.casefold() and needle not in row.body.casefold():
            continue
        history.append(
            {
                "item": row,
                "time": datetime.fromisoformat(row.recorded_at),
                "first": previous is None,
                "text_changed": previous
                and (row.title, row.body) != (previous.title, previous.body),
                "source_changed": previous and row.source_digest != previous.source_digest,
                "reply_changed": previous and row.reply_digest != previous.reply_digest,
            }
        )
    distinct = before.revision != after.revision
    source_changed = before.source_digest != after.source_digest
    reply_changed = before.reply_digest != after.reply_digest
    evidence = [_evidence(state, after)]
    if source_changed or reply_changed:
        evidence.insert(0, _evidence(state, before))
    context.update(
        before=before,
        after=after,
        distinct=distinct,
        history=history[::-1],
        evidence=evidence,
        source_changed=source_changed,
        reply_changed=reply_changed,
        text_changed=(before.title, before.body) != (after.title, after.body),
        fields=(
            _text_pair("العنوان", before.title, after.title),
            _text_pair("نص الجواب", before.body, after.body),
        ),
    )
    return render(request, TEMPLATE, context)
