"""Unmounted, default-off loopback diagnostics. No public writes or role lookup."""

import os

from django.core.exceptions import TooManyFieldsSent
from django.http import Http404, JsonResponse

from apps.editorial_demo.views import local_only

from . import services


def _response(decision, status):
    return JsonResponse(
        services.report(decision),
        status=status,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
        json_dumps_params={"ensure_ascii": False},
    )


def inspect(request, *, evaluate=False):
    # Guard before reading query fields or touching any source, even standalone.
    try:
        local_only(request)
        if os.environ.get("FATWA_FAST9_CASE_POLICY_JOIN") != "1":
            raise Http404
    except Http404:
        return _response(services.rejected("LOCAL_ONLY_DISABLED"), 404)
    if request.method not in {"GET", "HEAD"}:
        response = _response(services.rejected("METHOD_NOT_ALLOWED"), 405)
        response["Allow"] = "GET, HEAD"
        return response
    try:
        if len(request.META.get("QUERY_STRING", "")) > 3 * services.MAX_RECEIPT_BYTES + 2048:
            raise ValueError
        query = request.GET
        required = {"case_key", "actor", "action", "resource"}
        if evaluate:
            required.add("receipt")
        if not required <= set(query) or set(query) - (required | {"target_state"}):
            raise ValueError
        if any(len(query.getlist(key)) != 1 for key in query):
            raise ValueError
        params = {key: query[key] for key in ("case_key", "actor", "action", "resource")}
        params["target_state"] = query.get("target_state")
        decision = services.inspect_request(
            **params, receipt_text=query["receipt"] if evaluate else None
        )
    except (ValueError, UnicodeError, TooManyFieldsSent):
        return _response(services.rejected("INVALID_PARAMETERS"), 400)
    status = {"VERIFIED": 200, "REJECTED": 400, "NOT_CONNECTED": 503}[decision.synthetic_context]
    return _response(decision, status)
