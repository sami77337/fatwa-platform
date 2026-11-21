"""GET/HEAD only; serialize inside retained source guards, including error boundaries."""

from functools import wraps
from hashlib import sha256

from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from apps.casework.services import CaseConflict
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.library_preview import services as preview
from apps.library_preview.guard import boundary, private
from apps.research_library.editor import LABELS

from . import services
from .schema import contract


def failure(status):
    codes = {400: "invalid_request", 403: "request_denied", 404: "unavailable", 405: "method_not_allowed"}
    response = JsonResponse({"schema": services.SCHEMA, "error": {"code": codes.get(status, "unavailable")}}, status=status)
    if status == 405:
        response["Allow"] = "GET, HEAD"
    return private(response)


def safe_api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        denied = boundary(request)
        if denied is not None:
            return failure(denied.status_code)
        try:
            services.enabled()
            response = view(request, *args, **kwargs)
            services.enabled()
        except preview.InvalidFilter:
            return failure(400)
        except (preview.PreviewUnavailable, CaseConflict, DatabaseError, SyntheticWriteDenied):
            return failure(404)
        response["X-Material-API-Version"] = "1"
        return private(response)
    return wrapped


def no_query(request):
    if request.GET:
        raise preview.InvalidFilter()


@safe_api
def index(request):
    params = services.query_params(request.GET)
    with services.projection() as snapshot:
        return JsonResponse(services.catalogue(snapshot, params), json_dumps_params={"ensure_ascii": False})


@safe_api
def detail(request, public_id, number):
    no_query(request)
    with services.projection() as snapshot:
        return JsonResponse({"schema": services.SCHEMA, "material": services.record(snapshot, snapshot.locate(public_id, number))}, json_dumps_params={"ensure_ascii": False})


@safe_api
def original(request, public_id, number):
    no_query(request)
    with services.projection() as snapshot:
        row = snapshot.locate(public_id, number)
        result = snapshot.content(row["version_id"], usage="DOWNLOAD")
        response = HttpResponse(result["raw"], content_type=result["media_type"])
        extension = result["filename"].rsplit(".", 1)[-1]
        response["Content-Disposition"] = f'attachment; filename="material-{row["id"]}-v{row["number"]}.{extension}"'
        response["X-Content-SHA256"] = sha256(result["raw"]).hexdigest()
        return response


@safe_api
def schema(request):
    no_query(request)
    return JsonResponse(contract(), json_dumps_params={"ensure_ascii": False})


@safe_api
def docs(request):
    params = services.query_params(request.GET)
    with services.projection() as snapshot:
        data = services.catalogue(snapshot, params)
        return render(request, "material_api/docs.html", {"data": data, "kinds": LABELS})
