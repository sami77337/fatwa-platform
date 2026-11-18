"""Native scoped staff forms; the audio endpoint never accepts a case capability in a URL."""

from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import denied, private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import services
from .guard import boundary
from .models import TimedCitation

ACTIONS = {
    "timed_desk",
    "timed_propose",
    "timed_confirm",
    "timed_withdraw",
    "timed_open",
    "timed_preview",
}
SALT = "timed-citations.exact-source.v1"


def _staff(request):
    directory = _provider()
    actor = current_staff(request, directory)
    return actor, RequestDirectory(
        directory, actor, authenticated_provider_id=directory.provider_id
    )


@sensitive_post_parameters()
@csrf_protect
def workspace(request):
    try:
        services._enabled()
        if request.method != "POST" or request.POST.get("action") not in ACTIONS:
            raise InvalidForm("timed_form_invalid")
        action = request.POST["action"]
        required = {"action", "case_ref"}
        if action == "timed_propose":
            required |= {
                "source_pin",
                "start_ms",
                "end_ms",
                "reason",
                "replaces_id",
                "revision",
                "evidence_version",
            }
        elif action != "timed_desk":
            required |= {"citation_id"}
            if action in {"timed_confirm", "timed_withdraw"}:
                required.add("confirm")
        if action == "timed_preview" and "context_ms" in request.POST:
            required.add("context_ms")
        fields = _form(request, required)
        actor, provider = _staff(request)
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        selected = next(
            (row for row in cases.list_cases(**common) if row["public_ref"] == fields["case_ref"]),
            None,
        )
        if selected is None:
            return denied("timed_unavailable", 404)
        common["case_id"] = selected["case_id"]
        if action == "timed_propose":
            try:
                pin = signing.loads(fields["source_pin"], salt=SALT, max_age=1800)
            except signing.BadSignature as exc:
                raise InvalidForm("timed_pin_invalid") from exc
            services.propose(
                **common,
                source_pin=pin,
                start_ms=0 if fields["start_ms"] == "0" else _integer(fields["start_ms"]),
                end_ms=_integer(fields["end_ms"]),
                reason=fields["reason"],
                replaces_id=fields["replaces_id"] or None,
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
            )
        elif action in {"timed_confirm", "timed_withdraw"}:
            services.act(
                **common,
                citation_id=fields["citation_id"],
                action="CONFIRM" if action == "timed_confirm" else "WITHDRAW",
                confirmed=fields["confirm"] == "yes",
            )
        projection = services.desk(**common)
        for source in projection["sources"]:
            source["token"] = signing.dumps(source, salt=SALT, compress=True)
        if action in {"timed_open", "timed_preview"}:
            opened = services.open_audio(
                **common,
                citation_id=fields["citation_id"],
                review=action == "timed_preview",
                context_ms=0
                if fields.get("context_ms", "0") == "0"
                else _integer(fields["context_ms"]),
            )
            projection["preview"] = {key: value for key, value in opened.items() if key != "raw"}
            projection["player_url"] = (
                reverse(
                    "timed_review_audio" if action == "timed_preview" else "timed_audio",
                    args=[fields["citation_id"]],
                )
                + f"#t={opened['preview_start_ms'] / 1000:g},{opened['preview_end_ms'] / 1000:g}"
            )
        get_token(request)
        return private(render(request, "timed_citations/desk.html", projection))
    except (InvalidForm, SuspiciousOperation, ValueError) as exc:
        # Domain denials are uniform and contain no source IDs/names/durations.
        return denied("timed_unavailable", 404 if isinstance(exc, cases.CaseConflict) else 400)
    except IdentityUnavailable:
        return denied("timed_unavailable", 403)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("timed_unavailable", 503)


def audio(request, citation_id, *, review=False):
    refused = boundary(request)
    if refused:
        return refused
    try:
        actor, provider = _staff(request)
        row = TimedCitation.objects.filter(pk=citation_id).only("case_id").first()
        if row is None:
            return denied("timed_unavailable", 404)
        opened = services.open_audio(
            case_id=row.case_id,
            subject_id=actor.subject_id,
            provider=provider,
            citation_id=citation_id,
            review=review,
            synthetic_fixtures_only=True,
        )
        response = HttpResponse(
            b"" if request.method == "HEAD" else opened["raw"], content_type=opened["media_type"]
        )
        response["Content-Disposition"] = (
            'inline; filename="recording.wav"' if opened["media_type"] == "audio/wav" else "inline"
        )
        response["Content-Length"] = len(opened["raw"])
        response["Accept-Ranges"] = "none"
        return private(response)
    except (cases.CaseConflict, IdentityUnavailable):
        return denied("timed_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("timed_unavailable", 503)


def review_audio(request, citation_id):
    return audio(request, citation_id, review=True)
