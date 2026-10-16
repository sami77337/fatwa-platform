"""Server-rendered entry pages using bounded, existing catalog reads only."""

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.reference.query import Page
from apps.reference.services import CatalogUnavailable, list_books


@require_safe
def home(request: HttpRequest) -> HttpResponse:
    context: dict[str, object] = {
        "current_page": "home",
        "catalog_state": "unavailable",
        "source": None,
    }
    try:
        books = list_books(Page(1))
        if books.total == 1:
            context["catalog_state"] = "available"
            context["source"] = books.items[0]["work"]["title_original"]
        else:
            # Do not silently choose a source or expose an edition selector here.
            context["catalog_state"] = "multiple" if books.total else "empty"
    except (DatabaseError, CatalogUnavailable):
        # Keep the public entry and help reachable without exposing database errors.
        pass
    return render(request, "public_site/home.html", context)


@require_safe
def help_page(request: HttpRequest) -> HttpResponse:
    return render(request, "public_site/help.html", {"current_page": "help"})
