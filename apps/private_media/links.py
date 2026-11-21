"""Short-lived locators bound to a current browser, never bearer permissions.

The closed route inventory contains private byte readers only. Issuance invokes
the same real domain reader as consumption; every use repeats it under the case
lock. Domain projections can retain their pure final checks through the final
range/HEAD response. Neither a URL nor a cached response grants access.
"""

import copy
import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import wraps
from hashlib import sha256
from hmac import compare_digest
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.apps import apps
from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse, QueryDict
from django.urls import Resolver404, resolve
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web import access, requester_workspace
from apps.casework_web.guard import denied, private
from apps.delivery_queue.models import RequesterTrackingToken
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable
from apps.platform_recovery.integration import mutation_service

SALT = "fatwa.private-media.current-session.v1"
UUID = r"(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
ROUTES = (
    (
        rf"/casework/(?P<audience>staff|status)/attachments/{UUID}/",
        "case_attachments.CaseAttachment",
        "case_id",
    ),
    (
        rf"/casework/(?P<audience>staff|status)/answer-media/{UUID}/",
        "answer_media.AnswerPart",
        "manifest__answer__case_id",
    ),
    (
        rf"/casework/staff/library/{UUID}/(?P<use>file|download)/",
        "research_library.LibraryVersion",
        "item__case_id",
    ),
    (
        rf"/casework/staff/recording-parts/{UUID}/audio/",
        "answer_media.AnswerPart",
        "manifest__answer__case_id",
    ),
    (
        rf"/casework/staff/recording-transcripts/{UUID}/audio/",
        "public_answer_media.RecordingTranscript",
        "case_id",
    ),
    (
        rf"/casework/staff/timed-citations/{UUID}/(?P<use>audio|review-audio)/",
        "timed_citations.TimedCitation",
        "case_id",
    ),
    (
        rf"/casework/staff/pdf-citations/{UUID}/(?P<use>document|review-document|page|review-page)/",
        "pdf_citations.PdfCitation",
        "case_id",
    ),
    (
        rf"/casework/precise-citations/sources/{UUID}/file/",
        "precise_citations.CitationAnchor",
        "citation_set__answer__case_id",
    ),
)
_CHECKS = ContextVar("private_media_link_projection_checks", default=())
_QUERY = re.compile(r"[A-Za-z0-9_:-]{32,1800}")


def enabled():
    return getattr(settings, "FATWA_PRIVATE_MEDIA_LINKS_ENABLED", False) is True


def route(path):
    if type(path) is not str:
        return None
    for expression, model, case_field in ROUTES:
        match = re.fullmatch(expression, path)
        if match:
            return model, case_field, match.groupdict()
    return None


def admits_query(request):
    """Guard admission only; preserve the raw query and require canonical parsing.

    No decoding aliases, duplicate keys, extras or unregistered routes are allowed.
    Ticket integrity, browser binding and domain authorization remain view duties.
    """
    if not enabled() or request.method not in {"GET", "HEAD"} or route(request.path) is None:
        return False
    raw = request.META.get("QUERY_STRING", "")
    if type(raw) is not str or not 1 <= len(raw) <= 1900:
        return False
    try:
        fields = request.GET
        values = fields.getlist("access")
        return (
            set(fields) == {"access"}
            and len(values) == 1
            and _QUERY.fullmatch(values[0]) is not None
            and raw == urlencode({"access": values[0]})
        )
    except (ValueError, SuspiciousOperation):
        return False


def _configuration():
    key = getattr(settings, "FATWA_PRIVATE_MEDIA_LINKS_KEY", None)
    epoch = getattr(settings, "FATWA_PRIVATE_MEDIA_LINKS_EPOCH", None)
    ttl = getattr(settings, "FATWA_PRIVATE_MEDIA_LINKS_TTL_SECONDS", None)
    if (
        not enabled()
        or os.environ.get("FATWA_PRODUCTION") != "0"
        or type(key) is not str
        or not 32 <= len(key) <= 512
        or not key.strip()
        or key == settings.SECRET_KEY
        or type(epoch) is not str
        or re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", epoch) is None
        or type(ttl) is not int
        or not 1 <= ttl <= 900
    ):
        raise cases.CaseConflict("private_media_link_configuration_required")
    return key, epoch, ttl


def _hash(key, purpose, value):
    return salted_hmac(SALT + "." + purpose, value, secret=key, algorithm="sha256").hexdigest()


def _signer(config):
    return signing.TimestampSigner(key=config[0], salt=SALT, fallback_keys=[])


def retain_projection(check):
    """Retain only a domain's pure final pins, without caching its permissions."""
    for checks in _CHECKS.get():
        checks.append(check)


def _cookie_deadline(cookie, ttl):
    # The caller has already verified this signed session with its original salt.
    try:
        return datetime.fromtimestamp(signing.b62_decode(cookie.rsplit(":", 2)[1]) + ttl, UTC)
    except (ValueError, IndexError, OverflowError) as exc:
        raise cases.CaseConflict("private_media_session_required") from exc


def _source_pin(model, identifier):
    """Pure metadata/action snapshot; full bytes are verified by the domain reader."""
    fields = [
        field.attname
        for field in model._meta.concrete_fields
        if field.get_internal_type() != "BinaryField"
    ]
    row = model.objects.filter(pk=identifier).first()
    if row is None:
        raise cases.CaseConflict("private_media_source_unavailable")
    actions = []
    for name in ("actions", "decisions"):
        relation = getattr(row, name, None)
        if relation is not None and hasattr(relation, "all"):
            actions.append((name, list(relation.all().order_by("pk").values())))
    return list(model.objects.filter(pk=identifier).values(*fields)), actions


def _reader_flags(model_name):
    specific = {
        "case_attachments.CaseAttachment": (
            "FATWA_CASE_ATTACHMENTS_ENABLED",
            "FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED",
        ),
        "answer_media.AnswerPart": (
            "FATWA_ANSWER_MEDIA_ENABLED",
            "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED",
            "FATWA_ANSWER_LINKS_ENABLED",
            "FATWA_ANSWER_RELATED_ENABLED",
        ),
        "research_library.LibraryVersion": ("FATWA_RESEARCH_LIBRARY_ENABLED",),
        "public_answer_media.RecordingTranscript": ("FATWA_PUBLIC_ANSWER_MEDIA_ENABLED",),
        "timed_citations.TimedCitation": ("FATWA_TIMED_CITATIONS_ENABLED",),
        "pdf_citations.PdfCitation": ("FATWA_PDF_CITATIONS_ENABLED",),
        "precise_citations.CitationAnchor": ("FATWA_PRECISE_CITATIONS_ENABLED",),
    }
    names = (*specific[model_name], "FATWA_SOURCE_RIGHTS_ENABLED", "FATWA_SOURCE_RIGHTS_ENFORCED")
    return tuple(
        (name, type(getattr(settings, name, None)), getattr(settings, name, None)) for name in names
    )


@contextmanager
def _projection(request, spec, config, *, ticket_expires=None):
    """Hold the existing canonical lock until every response pin has been checked."""
    from apps.answer_media.editor_boundary import identity_snapshot
    from apps.source_rights.services import projection_expiry_guard

    model_name, field, captured = spec
    try:
        model = apps.get_model(model_name)
        case_id = model.objects.filter(pk=captured["id"]).values_list(field, flat=True).first()
    except (LookupError, ValueError) as exc:
        raise cases.CaseConflict("private_media_source_unavailable") from exc
    if case_id is None:
        raise cases.CaseConflict("private_media_source_unavailable")
    audience = captured.get("audience", "staff")
    csrf = request.META.get("CSRF_COOKIE", "")
    if type(csrf) is not str or not csrf:
        raise cases.CaseConflict("private_media_session_required")
    if audience == "status":
        capability = requester_workspace._capability(request)
        cookie = request.COOKIES.get(requester_workspace.COOKIE, "")
        token_digest = cases._digest(capability)
        initial = tuple(RequesterTrackingToken.objects.filter(pk=token_digest).values_list())
        grant = RequesterTrackingToken.objects.filter(pk=token_digest).first()
        if grant is None:
            raise cases.CaseConflict("private_media_session_required")
        deadline = min(grant.expires_at, _cookie_deadline(cookie, requester_workspace.TTL))
        principal = [audience, token_digest]
        locked = cases._token_case(capability, True)

        def session_check():
            if (
                tuple(RequesterTrackingToken.objects.filter(pk=token_digest).values_list())
                != initial
            ):
                raise cases.CaseConflict("private_media_session_changed")

    else:
        provider = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        initial = identity_snapshot(provider)
        actor = access.current_staff(request, provider)
        cookie = request.COOKIES.get(access.COOKIE, "")
        saved = json.loads(
            request.get_signed_cookie(access.COOKIE, salt=access.SALT, max_age=access.TTL)
        )
        deadline = min(actor.valid_until, datetime.fromisoformat(saved["until"]))
        principal = [audience, provider.provider_id, actor.subject_id, actor.auth_epoch]
        directory = access.RequestDirectory(
            provider, actor, authenticated_provider_id=provider.provider_id
        )
        locked = cases._staff_case(case_id, actor.subject_id, directory, True)

        def session_check():
            if (
                getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not provider
                or identity_snapshot(provider) != initial
            ):
                raise cases.CaseConflict("private_media_session_changed")

    binding = _hash(
        config[0], "browser", json.dumps([principal, cookie, csrf], separators=(",", ":"))
    )
    checks = []
    token = _CHECKS.set((*_CHECKS.get(), checks))
    storage = getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)
    try:
        with synthetic_queue_atomic():
            with locked as current, projection_expiry_guard():
                case = current[0] if audience == "staff" else current
                if str(case.pk) != str(case_id):
                    raise cases.CaseConflict("private_media_case_mismatch")
                state = list(Case.objects.filter(pk=case_id).values())
                source_state = _source_pin(model, captured["id"])
                flags = _reader_flags(model_name)
                session_check()
                yield binding, deadline
            # All nested authorization/storage callbacks have now completed.
            for check in checks:
                check()
            session_check()
            if (
                _configuration() != config
                or getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None) is not storage
                or list(Case.objects.filter(pk=case_id).values()) != state
                or _source_pin(model, captured["id"]) != source_state
                or _reader_flags(model_name) != flags
                or timezone.now() >= deadline
                or (ticket_expires is not None and timezone.now().timestamp() >= ticket_expires)
            ):
                raise cases.CaseConflict("private_media_projection_changed")
    finally:
        _CHECKS.reset(token)


def _request_for_source(request, path):
    """Explicit internal full-byte read, never a mutation of the incoming request."""
    source = copy.copy(request)
    source.META = request.META.copy()
    source.COOKIES = request.COOKIES.copy()
    source.method, source.path, source.path_info = "GET", path, path
    source.META["QUERY_STRING"] = ""
    for name in ("HTTP_RANGE", "HTTP_IF_RANGE", "HTTP_IF_NONE_MATCH", "HTTP_IF_MODIFIED_SINCE"):
        source.META.pop(name, None)
    source.GET, source.POST = QueryDict(""), QueryDict("")
    return source


def _source_response(reader, request, path, args, kwargs):
    response = reader(_request_for_source(request, path), *args, **kwargs)
    if response.status_code != 200 or getattr(response, "streaming", False):
        raise cases.CaseConflict("private_media_source_unavailable")
    return response


def _source_digest(config, path, response):
    value = json.dumps(
        [
            path,
            sha256(response.content).hexdigest(),
            response.get("Content-Type", ""),
            response.get("Content-Disposition", ""),
        ],
        separators=(",", ":"),
    )
    return _hash(config[0], "source", value)


def _purposes(path):
    if "/attachments/" in path or "/answer-media/" in path:
        return {"INLINE", "DOWNLOAD"}
    return {"DOWNLOAD" if path.endswith("/download/") else "INLINE"}


@mutation_service
def issue(request, url, *, purpose="INLINE"):
    """Called by a native authorized page, with its real session and domain reader."""
    if not enabled():
        return url
    config = _configuration()
    target = urlsplit(url)
    spec = route(target.path)
    if (
        target.scheme
        or target.netloc
        or target.query
        or spec is None
        or purpose not in _purposes(target.path)
    ):
        raise cases.CaseConflict("private_media_link_target_invalid")
    try:
        match = resolve(target.path)
        reader = getattr(match.func, "_private_media_source_view", None)
        if not callable(reader):
            raise cases.CaseConflict("private_media_reader_unregistered")
        with _projection(request, spec, config) as (binding, deadline):
            response = _source_response(reader, request, target.path, match.args, match.kwargs)
            now = timezone.now()
            payload = {
                "v": 1,
                "p": target.path,
                "u": purpose,
                "b": binding,
                "k": config[1],
                "s": _source_digest(config, target.path, response),
                "i": int(now.timestamp()),
                "x": int(min(now + timedelta(seconds=config[2]), deadline).timestamp()),
            }
            ticket = _signer(config).sign_object(payload)
            if _QUERY.fullmatch(ticket) is None:
                raise cases.CaseConflict("private_media_link_bound")
            value = urlunsplit(
                ("", "", target.path, urlencode({"access": ticket}), target.fragment)
            )
            if len(value) > 2048:
                raise cases.CaseConflict("private_media_link_bound")
        if timezone.now().timestamp() >= payload["x"]:
            raise cases.CaseConflict("private_media_ticket_expired")
        return value
    except (Resolver404, signing.BadSignature, IdentityUnavailable) as exc:
        raise cases.CaseConflict("private_media_source_unavailable") from exc


def _payload(request, config):
    if not admits_query(request):
        raise cases.CaseConflict("private_media_ticket_required")
    try:
        value = _signer(config).unsign_object(request.GET["access"], max_age=config[2])
    except (signing.BadSignature, ValueError, TypeError, UnicodeError) as exc:
        raise cases.CaseConflict("private_media_ticket_invalid") from exc
    now = timezone.now().timestamp()
    if (
        type(value) is not dict
        or set(value) != {"v", "p", "u", "b", "k", "s", "i", "x"}
        or type(value["v"]) is not int
        or value["v"] != 1
        or value["p"] != request.path
        or value["k"] != config[1]
        or type(value["u"]) is not str
        or value["u"] not in _purposes(request.path)
        or any(
            type(value[name]) is not str or re.fullmatch(r"[a-f0-9]{64}", value[name]) is None
            for name in ("b", "s")
        )
        or type(value["i"]) is not int
        or type(value["x"]) is not int
        or not value["i"] <= now < value["x"] <= value["i"] + config[2]
    ):
        raise cases.CaseConflict("private_media_ticket_invalid")
    return value


def _range_response(request, source, purpose):
    raw = source.content
    size, etag = len(raw), '"' + sha256(raw).hexdigest() + '"'
    body, status, span = raw, 200, None
    requested = request.headers.get("Range")
    if (
        request.method == "GET"
        and requested is not None
        and request.headers.get("If-Range", etag) == etag
    ):
        match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", requested)
        valid = match is not None and bool(match[1] or match[2]) and size > 0
        start, end = 0, size - 1
        if valid:
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), size - 1) if match[2] else size - 1
                valid = start <= end and start < size
            else:
                suffix = int(match[2])
                valid, start = suffix > 0, max(0, size - suffix)
        if valid:
            body, status, span = raw[start : end + 1], 206, f"bytes {start}-{end}/{size}"
        else:
            body, status, span = b"", 416, f"bytes */{size}"
    response = HttpResponse(body, status=status, headers=dict(source.headers))
    if purpose == "DOWNLOAD":
        disposition = source.get("Content-Disposition", "inline; filename=source")
        response["Content-Disposition"] = (
            "attachment" + disposition[disposition.find(";") :]
            if ";" in disposition
            else "attachment"
        )
    response["Accept-Ranges"], response["ETag"] = "bytes", etag
    response["Content-Length"] = str(len(body))
    response["Content-Security-Policy"] = "sandbox; default-src 'none'; frame-ancestors 'self'"
    if span:
        response["Content-Range"] = span
    response = private(response, head=request.method == "HEAD")
    response["Referrer-Policy"] = "no-referrer"
    return response


def protect(view):
    @wraps(view)
    @mutation_service
    def protected(request, *args, **kwargs):
        spec = route(request.path)
        if not enabled() or spec is None:
            return view(request, *args, **kwargs)
        try:
            if request.method not in {"GET", "HEAD"}:
                return denied("private_media_unavailable", 405)
            config = _configuration()
            payload = _payload(request, config)
            original_query = request.META["QUERY_STRING"]
            with _projection(request, spec, config, ticket_expires=payload["x"]) as (binding, _):
                if not compare_digest(binding, payload["b"]):
                    raise cases.CaseConflict("private_media_session_changed")
                source = _source_response(view, request, request.path, args, kwargs)
                if not compare_digest(_source_digest(config, request.path, source), payload["s"]):
                    raise cases.CaseConflict("private_media_source_changed")
                response = _range_response(request, source, payload["u"])
                if timezone.now().timestamp() >= payload["x"]:
                    raise cases.CaseConflict("private_media_ticket_expired")
            if request.META.get("QUERY_STRING") != original_query or not admits_query(request):
                raise cases.CaseConflict("private_media_query_changed")
            return response
        except (
            cases.CaseConflict,
            IdentityUnavailable,
            ValueError,
            TypeError,
            SuspiciousOperation,
        ):
            response = denied("private_media_unavailable", 404)
        except (DatabaseError, SyntheticWriteDenied):
            response = denied("private_media_store_unavailable", 503)
        response["Referrer-Policy"] = "no-referrer"
        return response

    protected._private_media_source_view = view
    return protected


class PrivateMediaResponses:
    """Final privacy headers only. Never alter queries, dispatch, auth or methods."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        protected = enabled() and route(request.path) is not None
        response = self.get_response(request)
        if protected:
            response["Referrer-Policy"] = "no-referrer"
            response["Cache-Control"] = "private, no-store, max-age=0"
        return response
