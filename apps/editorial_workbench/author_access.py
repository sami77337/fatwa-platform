"""Access to the local human authoring desk and staff read-only history."""

from functools import wraps

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from .reviewer_access import signed_in


def draft_history_required(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if signed_in(request, "author") or signed_in(request):
            return view(request, *args, **kwargs)
        if request.method in {"GET", "HEAD"}:
            return HttpResponseRedirect(reverse("author_login"))
        return render(
            request,
            "editorial_workbench/reviewer_login.html",
            {"author_login": True, "message": "سجّل الدخول بهوية العامل المختص أولًا."},
            status=403,
        )

    return guarded
