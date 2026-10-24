"""Read-only HTTP composition of existing synthetic editorial services."""

from pathlib import Path
from urllib.parse import urlencode

from django.core.exceptions import TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template import engines
from django.urls import reverse
from django.views.decorators.http import require_safe

from apps.editorial_demo.views import local_only
from apps.fatwa_drafts.revision_audit import build_revision_audit
from apps.revision_core.revision_comparison import compare_revisions
from apps.revision_core.revision_history import (
    HistoryDataError,
    InvalidRevisionId,
    UnknownRevisionId,
    build_history,
    select_revisions,
)

from .packets import build_packet
from .services import WorkbenchDataError, build_cases, build_prepared_workbench

STATUSES = (("ready", "جاهز للعرض التحريري"), ("review", "يحتاج مراجعة"), ("blocked", "مدخل محجوب"))


def failure(request: HttpRequest, message: str, status: int) -> HttpResponse:
    response = render(
        request,
        "editorial_workbench/error.html",
        {
            "message": message,
            "status_code": status,
            "recovery_url": reverse("editorial_workbench:index"),
        },
        status=status,
    )
    response["Cache-Control"] = "no-store"
    return response


def _query(request: HttpRequest, *, detail: bool) -> tuple[str, str, str]:
    query = request.GET
    allowed = {"q", "status", "batch"} | (
        {"revision", "before", "after", "packet"} if detail else set()
    )
    q, status = query.get("q", ""), query.get("status", "")
    batch = query.get("batch", "")
    if (
        set(query) - allowed
        or any(len(query.getlist(key)) != 1 for key in query)
        or len(q) > 80
        or any(ord(c) < 32 or ord(c) == 127 for c in q)
        or status not in {"", *(code for code, _ in STATUSES)}
        or len(batch) > 100
        or any(not (c.isascii() and (c.isalnum() or c == "-")) for c in batch)
        or ("before" in query) != ("after" in query)
        or ("packet" in query and query["packet"] not in {"html", "json", "print"})
    ):
        raise ValueError("invalid_query")
    q.encode("utf-8", errors="strict")
    return q, status, batch


def _url(name: str, params: dict, key: str | None = None, anchor: str = "") -> str:
    base = reverse(name, args=[key] if key is not None else None)
    return base + ("?" + urlencode(params) if params else "") + ("#" + anchor if anchor else "")


@require_safe
def workbench(request: HttpRequest, key: str | None = None) -> HttpResponse:
    local_only(request)
    try:
        q, status, batch_id = _query(request, detail=key is not None)
    except (ValueError, UnicodeError, TooManyFieldsSent):
        return failure(
            request, "معايير غير صالحة. استخدم بحثًا حتى ٨٠ حرفًا واختر حالتين للمقارنة.", 400
        )
    try:
        all_cases = build_cases()
        prepared = build_prepared_workbench()
        all_cases += prepared.cases
    except WorkbenchDataError:
        return failure(request, "تعذر تحميل العينات الاصطناعية. عد إلى القائمة وأعد المحاولة.", 503)
    if batch_id and batch_id not in {entry.batch_id for entry in prepared.batches}:
        return failure(request, "الدفعة غير معروفة. اختر دفعة اصطناعية من القائمة.", 400)
    case = next((item for item in all_cases if item.key == key), None)
    if key is not None and case is None:
        return failure(request, "السجل الاصطناعي غير موجود. اختر سجلًا من القائمة.", 404)
    term = q.strip().casefold()
    cases = tuple(
        item
        for item in all_cases
        if (not status or item.status == status)
        and (not batch_id or getattr(item, "batch_id", None) == batch_id)
        and (not term or term in ((item.external_id or "") + (item.question or "")).casefold())
    )
    filters = {
        name: value for name, value in (("q", q), ("status", status), ("batch", batch_id)) if value
    }
    selected_batch = next(
        (
            entry
            for entry in prepared.batches
            if entry.batch_id == (getattr(case, "batch_id", None) or batch_id)
        ),
        None,
    )
    peers = tuple(
        item for item in cases if getattr(item, "batch_id", None) == getattr(case, "batch_id", None)
    )
    position = next((i for i, item in enumerate(peers) if item.key == key), None)
    neighbors = (
        ()
        if position is None
        else tuple(
            {
                "label": label,
                "case": peers[index],
                "url": _url("editorial_workbench:detail", filters, peers[index].key),
            }
            for label, index in (("السجل السابق", position - 1), ("السجل التالي", position + 1))
            if 0 <= index < len(peers)
        )
    )
    history, history_rows, revisions = (), (), ()
    selected = before = after = comparison = audit = None
    if case is not None and case.record is not None:
        try:
            history = build_history(case.record)
            revisions = tuple(entry.revision for entry in history)
            selected_id = request.GET.get("revision", str(revisions[-1].number))
            selected, _ = select_revisions(history, selected_id, selected_id)
            before, after = select_revisions(
                history,
                request.GET.get("before", str(revisions[0].number)),
                request.GET.get("after", str(revisions[-1].number)),
            )
            comparison = compare_revisions(before, after)
            audit = build_revision_audit(case.record, synthetic_fixtures_only=True)
        except InvalidRevisionId:
            return failure(request, "هوية المراجعة غير صالحة. اختر رقمًا من سجل المراجعات.", 400)
        except UnknownRevisionId:
            return failure(request, "المراجعة المطلوبة غير موجودة في هذا السجل الاصطناعي.", 404)
        except (HistoryDataError, ValueError, TypeError):
            return failure(request, "تعذر عرض سجل المراجعات الاصطناعي بأمان.", 503)
        history_rows = tuple(
            {
                "entry": entry,
                "url": _url(
                    "editorial_workbench:detail",
                    {
                        **filters,
                        "revision": entry.revision.number,
                        "before": before.number,
                        "after": after.number,
                    },
                    key,
                    "snapshot",
                ),
                "compare_url": _url(
                    "editorial_workbench:detail",
                    {
                        **filters,
                        "revision": selected.number,
                        "before": entry.previous_number or entry.revision.number,
                        "after": entry.revision.number,
                    },
                    key,
                    "comparison",
                )
                if entry.previous_number is not None
                else None,
            }
            for entry in history
        )
    elif case is not None and set(request.GET) & {"revision", "before", "after"}:
        return failure(request, "لا توجد مسودة أو مراجعات لهذا المدخل. راجع ملاحظات الاستلام.", 400)
    context = {
        "batches": prepared.batches,
        "batch_id": batch_id,
        "selected_batch": selected_batch,
        "neighbors": neighbors,
        "batch_panel": _owned_template("batches.html"),
        "reference_panel": _owned_template("references.html"),
        "cases": cases,
        "case": case,
        "q": q,
        "status": status,
        "statuses": STATUSES,
        "list_url": reverse("editorial_workbench:index"),
        "return_url": _url("editorial_workbench:index", filters),
        "detail_rows": tuple(
            {"case": item, "url": _url("editorial_workbench:detail", filters, item.key)}
            for item in cases
        ),
        "history_rows": history_rows,
        "revisions": revisions,
        "selected_revision": selected,
        "before_revision": before,
        "after_revision": after,
        "comparison": comparison,
        "audit": audit,
        "references": case.references if case else (),
        "compare_url": reverse("editorial_workbench:detail", args=[key]) if case else "",
        "hidden_filters": tuple(filters.items()),
        "selected_url": _url("editorial_workbench:detail", filters, key) if case else "",
        "summary": {
            "total": len(all_cases),
            **{code: sum(item.status == code for item in all_cases) for code, _ in STATUSES},
        },
        "stored_url": reverse("editorial_workbench:stored"),
    }
    if case is not None:
        selection = (
            {"revision": selected.number, "before": before.number, "after": after.number}
            if selected is not None
            else {}
        )
        packet_params = {**filters, **selection}
        context["packet_url"] = _url(
            "editorial_workbench:detail", {**packet_params, "packet": "html"}, key
        )
        if request.GET.get("packet"):
            try:
                packet = build_packet(
                    case,
                    selected_batch,
                    **{name: str(value) for name, value in selection.items()},
                )
            except (WorkbenchDataError, HistoryDataError, ValueError, TypeError, UnicodeError):
                return failure(
                    request,
                    "تعذر إنشاء حزمة السجل كاملة بأمان. عد إلى السجل وراجع مصدر العينة.",
                    503,
                )
            if request.GET["packet"] == "json":
                response = HttpResponse(
                    packet.json_bytes, content_type="application/json; charset=utf-8"
                )
                response["Content-Disposition"] = (
                    f'attachment; filename="case-{case.key}-packet.json"'
                )
                response["X-Content-Type-Options"] = "nosniff"
            else:
                payload = packet.payload()
                context.update(
                    {
                        "packet": payload,
                        "packet_sha256": packet.sha256,
                        "packet_bytes": len(packet.json_bytes),
                        "print_mode": request.GET["packet"] == "print",
                        "workbench_url": _url("editorial_workbench:detail", packet_params, key),
                        "packet_json_url": _url(
                            "editorial_workbench:detail", {**packet_params, "packet": "json"}, key
                        ),
                        "packet_print_url": _url(
                            "editorial_workbench:detail", {**packet_params, "packet": "print"}, key
                        ),
                        "packet_intake_json": _packet_text(payload["intake"]),
                        "packet_reference_json": _packet_text(payload["reference_verification"]),
                        "packet_snapshots": tuple(
                            {
                                "snapshot": snapshot,
                                "references": _packet_text(snapshot["reference_links"]),
                            }
                            for snapshot in payload["snapshots"]
                        ),
                    }
                )
                response = render(request, "editorial_workbench/packet.html", context)
            response["Cache-Control"] = "no-store"
            response["X-Packet-SHA256"] = packet.sha256
            return response
    response = HttpResponse(_owned_template("workbench.html").render(context, request))
    response["Cache-Control"] = "no-store"
    return response


def _packet_text(value) -> str:
    """Labeled JSON presentation only; canonical export uses packet.json_bytes."""
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _owned_template(name: str):
    """Fixed lane-owned templates use the existing configured Django backend.

    Names are code constants, never request values. This keeps template changes
    in this lane without changing shared loader settings or app registration.
    """
    source = Path(__file__).with_name("templates").joinpath(name).read_text(encoding="utf-8")
    return engines["django"].from_string(source)


@require_safe
def stylesheet(request: HttpRequest) -> HttpResponse:
    local_only(request)
    try:
        if request.GET:
            return failure(request, "ملف التنسيق لا يقبل معايير إضافية.", 400)
        payload = Path(__file__).with_name("workbench.css").read_bytes()
    except TooManyFieldsSent:
        return failure(request, "معايير غير صالحة.", 400)
    except OSError:
        return failure(request, "تعذر تحميل تنسيق مساحة التحرير المحلية.", 503)
    response = HttpResponse(payload, content_type="text/css; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response
