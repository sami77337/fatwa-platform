"""Real native forms, bounded media responses and optional public attachments."""

import re
import uuid
from functools import wraps
from hashlib import sha256
from pathlib import Path

from django.core.exceptions import DisallowedHost, SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.guard import enabled as staff_enabled
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.library_preview import services as preview
from apps.library_preview.guard import safe_read
from apps.mufti_review.identity import IdentityUnavailable

from . import public, services
from .boundaries import enabled
from .models import RecordingTranscript

ACTIONS = {
    "pm_open",
    "pm_save_transcript",
    "pm_review_transcript",
    "pm_prepare_media",
    "pm_review_media",
}


def _zero(value):
    return 0 if value == "0" else _integer(value)


def _common(request, case_ref):
    directory = _provider()
    actor = current_staff(request, directory, case_key=case_ref)
    provider = RequestDirectory(directory, actor, authenticated_provider_id=directory.provider_id)
    row = Case.objects.filter(public_ref=case_ref).first()
    if row is None:
        raise cases.CaseConflict("recording_case_unavailable")
    return dict(
        case_id=str(row.pk),
        subject_id=actor.subject_id,
        provider=provider,
        synthetic_fixtures_only=True,
    )


def _fields(request, action):
    required = {"action", "case_ref"}
    if action != "pm_open":
        required |= {"revision", "evidence_version", "request_key", "note"}
    if action == "pm_save_transcript":
        required |= {"part_id", "text", "change_kind", "expected_version"}
        required |= {
            f"{name}_{index}"
            for index in range(services.MAX_SEGMENTS)
            for name in ("quote", "start_ms", "end_ms")
        }
    elif action == "pm_prepare_media":
        required |= {"part_id", "publication_id", "transcript_id", "label", "expected_version"}
    elif action in {"pm_review_transcript", "pm_review_media"}:
        required |= {
            "transcript_id" if action == "pm_review_transcript" else "edition_id",
            "command",
            "confirmed",
            "expected_actions",
        }
        if action == "pm_review_media":
            required.add("minutes")
    if request.method != "POST" or action not in ACTIONS or request.GET or request.FILES:
        raise InvalidForm("recording_form_invalid")
    return _form(request, required)


def _segments(fields):
    text, result = fields["text"], []
    for index in range(services.MAX_SEGMENTS):
        quote, start, end = (fields[f"{name}_{index}"] for name in ("quote", "start_ms", "end_ms"))
        if not quote and not start and not end:
            continue
        if not quote or text.count(quote) != 1:
            raise InvalidForm("recording_segment_quote_ambiguous")
        offset = text.index(quote)
        result.append(
            {
                "char_start": offset,
                "char_end": offset + len(quote),
                "start_ms": _zero(start),
                "end_ms": _integer(end),
            }
        )
    return result


def _page(request, common, message=""):
    with services.desk_projection(**common) as result:
        return private(
            render(
                request,
                "public_answer_media/desk.html",
                {"result": result, "request_key": str(uuid.uuid4()), "message": message},
            )
        )


@sensitive_post_parameters()
@csrf_protect
def workspace(request):
    try:
        enabled()
        action = request.POST.get("action", "")
        fields = _fields(request, action)
        common = _common(request, fields["case_ref"])
        with synthetic_queue_atomic():
            message = ""
            if action != "pm_open":
                pins = dict(
                    common,
                    expected_revision=_integer(fields["revision"]),
                    expected_evidence_version=_integer(fields["evidence_version"]),
                    note=fields["note"],
                    request_key=fields["request_key"],
                )
                if action == "pm_save_transcript":
                    services.save_transcript(
                        **pins,
                        part_id=fields["part_id"],
                        text=fields["text"],
                        segments=_segments(fields),
                        change_kind=fields["change_kind"],
                        expected_version=_zero(fields["expected_version"]),
                    )
                    message = "حُفظت نسخة جديدة. الأصل باقٍ، والنسخة الجديدة تحتاج إلى مراجعة مستقلة قبل إتاحتها."
                elif action == "pm_prepare_media":
                    services.prepare_media(
                        **pins,
                        part_id=fields["part_id"],
                        publication_id=fields["publication_id"],
                        transcript_id=fields["transcript_id"] or None,
                        label=fields["label"],
                        expected_version=_zero(fields["expected_version"]),
                    )
                    message = "حُفظ مرشح إتاحة التسجيل والتفريغ المحدد؛ لم يُنشر بعد."
                else:
                    kwargs = dict(
                        pins,
                        action=fields["command"],
                        confirmed=fields["confirmed"] == "yes",
                        expected_actions=_zero(fields["expected_actions"]),
                    )
                    if action == "pm_review_transcript":
                        services.review_transcript(**kwargs, transcript_id=fields["transcript_id"])
                    else:
                        services.review_media(
                            **kwargs,
                            edition_id=fields["edition_id"],
                            minutes=_zero(fields["minutes"]),
                        )
                    message = "حُفظ القرار على النسخة المحددة مع الفاعل والوقت."
            return _page(request, common, message)
    except IdentityUnavailable:
        return denied("recording_identity_required", 403)
    except cases.CaseConflict:
        return denied("recording_action_unavailable", 409)
    except (InvalidForm, SuspiciousOperation, ValueError, TypeError):
        return denied("recording_form_invalid", 400)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("recording_store_unavailable", 503)


def _private_read(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            enabled()
            # The same literal-loopback/authenticated native restrictions are
            # repeated here as well as in the coordinator's route inventory.
            if not staff_enabled() or request.method not in {"GET", "HEAD"} or request.GET:
                return denied("recording_unavailable", 404)
            if request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"} or any(
                key in request.META
                for key in ("HTTP_FORWARDED", "HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_HOST")
            ):
                return denied("recording_unavailable", 403)
            if (
                re.fullmatch(r"(?:127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", request.get_host())
                is None
            ):
                return denied("recording_unavailable", 400)
            return view(request, *args, **kwargs)
        except DisallowedHost:
            return denied("recording_unavailable", 400)
        except IdentityUnavailable:
            return denied("recording_unavailable", 403)
        except cases.CaseConflict:
            return denied("recording_unavailable", 404)
        except (DatabaseError, SyntheticWriteDenied):
            return denied("recording_store_unavailable", 503)

    return wrapped


def _file_response(request, data):
    # Authorization and the complete source hash have already been checked by
    # the surrounding projection. A range never bypasses those checks or reads
    # a different file. Chromium needs a genuine byte-range response to seek
    # within a reviewed original before the user starts playback.
    raw = data["raw"]
    size = len(raw)
    etag = '"' + sha256(raw).hexdigest() + '"'
    status, body, content_range = 200, raw, None
    requested = request.headers.get("Range")
    if (
        request.method == "GET"
        and requested is not None
        and request.headers.get("If-Range", etag) == etag
    ):
        match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", requested)
        start, end = 0, size - 1
        valid = match is not None and bool(match[1] or match[2]) and size > 0
        if valid:
            if not match[1]:
                suffix = int(match[2])
                valid = suffix > 0
                start = max(0, size - suffix)
            else:
                start = int(match[1])
                end = min(int(match[2]), size - 1) if match[2] else size - 1
                valid = start <= end and start < size
        if valid:
            status, body = 206, raw[start : end + 1]
            content_range = f"bytes {start}-{end}/{size}"
        else:
            # Multipart and malformed ranges are deliberately unsupported;
            # there is no dynamic file seek, multipart amplification or cache.
            status, body = 416, b""
            content_range = f"bytes */{size}"
    response = HttpResponse(body, status=status, content_type=data["media_type"])
    response["Content-Disposition"] = f'inline; filename="{data["filename"]}"'
    response["Content-Security-Policy"] = "sandbox; default-src 'none'; frame-ancestors 'none'"
    response["Content-Length"] = str(len(body))
    response["Accept-Ranges"] = "bytes"
    response["ETag"] = etag
    if content_range is not None:
        response["Content-Range"] = content_range
    return private(response, head=request.method == "HEAD")


@_private_read
def staff_audio(request, part_id=None, transcript_id=None):
    if part_id is not None:
        row = AnswerPart.objects.select_related("manifest__answer__case").filter(pk=part_id).first()
        if row is None:
            return denied("recording_unavailable", 404)
        common = _common(request, row.manifest.answer.case.public_ref)
        with services.audio_projection(**common, part_id=part_id) as result:
            return _file_response(request, result)
    row = RecordingTranscript.objects.select_related("case").filter(pk=transcript_id).first()
    if row is None:
        return denied("recording_unavailable", 404)
    common = _common(request, row.case.public_ref)
    with services.transcript_projection(**common, transcript_id=transcript_id) as result:
        return _file_response(request, result)


@_private_read
def staff_segment(request, transcript_id, index):
    row = RecordingTranscript.objects.select_related("case").filter(pk=transcript_id).first()
    if row is None:
        return denied("recording_unavailable", 404)
    common = _common(request, row.case.public_ref)
    with services.segment_projection(**common, transcript_id=transcript_id, index=index) as result:
        response = render(request, "public_answer_media/staff_segment.html", {"segment": result})
        response._allow_recording_player = True
        return private(response)


def _player_script():
    raw = (Path(__file__).parent / "static" / "public_answer_media" / "player.mjs").read_bytes()
    return HttpResponse(raw, content_type="text/javascript; charset=utf-8")


@_private_read
def staff_player(request):
    current_staff(request, _provider())
    return private(_player_script(), head=request.method == "HEAD")


@safe_read
def public_player(request):
    if request.GET:
        raise preview.InvalidFilter()
    try:
        enabled()
    except cases.CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc
    from django.conf import settings

    if getattr(settings, "FATWA_PUBLIC_ANSWER_MEDIA_PUBLIC_ENABLED", False) is not True:
        raise preview.PreviewUnavailable()
    return _player_script()


def _public_render(request, result, *, unavailable=False, segment=None):
    response = render(
        request,
        "public_answer_media/publication.html",
        {
            "publication": result["publication"],
            "recordings": result.get("recordings", []),
            "unavailable": unavailable,
            "segment": segment,
        },
    )
    response._allow_library_media = True
    if segment is not None:
        response._allow_recording_player = True
    return response


@safe_read
def publication_detail(request, publication_id):
    if request.GET:
        raise preview.InvalidFilter()
    try:
        with public.publication_projection(publication_id) as result:
            return _public_render(request, result)
    except public.OptionalMediaUnavailable:
        # One bounded fresh read, never reuse text from a failed media projection.
        with public.publication_projection(publication_id, include_media=False) as result:
            return _public_render(request, result, unavailable=True)


@safe_read
def public_audio(request, media_id):
    if request.GET:
        raise preview.InvalidFilter()
    with public.recording_projection(media_id) as result:
        return _file_response(request, result["file"])


@safe_read
def public_segment(request, media_id, index):
    if request.GET:
        raise preview.InvalidFilter()
    with public.recording_projection(media_id) as result:
        segments = result["recording"]["segments"]
        if not 0 <= index < len(segments):
            raise preview.PreviewUnavailable()
        return _public_render(
            request, {"publication": result["publication"]}, segment=segments[index]
        )
