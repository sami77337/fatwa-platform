"""Native scoped staff forms; the PDF endpoint never accepts a case capability in a URL."""

from django.core import signing
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError
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
from .models import PdfCitation

ACTIONS = {
    "pdf_desk",
    "pdf_propose",
    "pdf_confirm",
    "pdf_withdraw",
    "pdf_open",
    "pdf_preview",
}
SALT = "pdf-citations.exact-source.v1"


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
            raise InvalidForm("pdf_form_invalid")
        action = request.POST["action"]
        required = {"action", "case_ref"}
        if action == "pdf_propose":
            required |= {
                "source_pin",
                "page_number",
                "printed_label",
                "printed_confirmed",
                "reason",
                "replaces_id",
                "revision",
                "evidence_version",
            }
        elif action != "pdf_desk":
            required |= {"citation_id"}
            if action in {"pdf_confirm", "pdf_withdraw"}:
                required.add("confirm")
        fields = _form(request, required)
        actor, provider = _staff(request)
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        selected = next(
            (row for row in cases.list_cases(**common) if row["public_ref"] == fields["case_ref"]),
            None,
        )
        if selected is None:
            return denied("pdf_unavailable", 404)
        common["case_id"] = selected["case_id"]
        if action == "pdf_propose":
            if fields["printed_confirmed"] not in {"yes", "no"}:
                raise InvalidForm("pdf_mapping_invalid")
            try:
                pin = signing.loads(fields["source_pin"], salt=SALT, max_age=1800)
            except signing.BadSignature as exc:
                raise InvalidForm("pdf_pin_invalid") from exc
            services.propose(
                **common,
                source_pin=pin,
                page_number=_integer(fields["page_number"]),
                printed_label=fields["printed_label"],
                printed_confirmed=fields["printed_confirmed"] == "yes",
                reason=fields["reason"],
                replaces_id=fields["replaces_id"] or None,
                expected_revision=_integer(fields["revision"]),
                expected_evidence_version=_integer(fields["evidence_version"]),
            )
        elif action in {"pdf_confirm", "pdf_withdraw"}:
            services.act(
                **common,
                citation_id=fields["citation_id"],
                action="CONFIRM" if action == "pdf_confirm" else "WITHDRAW",
                confirmed=fields["confirm"] == "yes",
            )
        projection = services.desk(**common)
        for source in projection["sources"]:
            source["token"] = signing.dumps(source, salt=SALT, compress=True)
        if action in {"pdf_open", "pdf_preview"}:
            opened = services.open_pdf(
                **common, citation_id=fields["citation_id"], review=action == "pdf_preview"
            )
            projection["player_url"] = (
                reverse(
                    "pdf_review_document" if action == "pdf_preview" else "pdf_document",
                    args=[fields["citation_id"]],
                )
                + f"#page={opened['page_number']}"
            )
        get_token(request)
        return private(render(request, "pdf_citations/desk.html", projection))
    except (InvalidForm, SuspiciousOperation, ValueError) as exc:
        # Domain denials are uniform and contain no source IDs/names/page labels.
        return denied("pdf_unavailable", 404 if isinstance(exc, cases.CaseConflict) else 400)
    except IdentityUnavailable:
        return denied("pdf_unavailable", 403)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("pdf_unavailable", 503)


def document(request, citation_id, *, review=False):
    refused = boundary(request)
    if refused:
        return refused
    try:
        actor, provider = _staff(request)
        row = PdfCitation.objects.filter(pk=citation_id).only("case_id").first()
        if row is None:
            return denied("pdf_unavailable", 404)
        opened = services.open_pdf(
            case_id=row.case_id,
            subject_id=actor.subject_id,
            provider=provider,
            citation_id=citation_id,
            review=review,
            synthetic_fixtures_only=True,
        )
        # Reuse the existing private-original response, including its sandbox CSP.
        from apps.case_attachments.views import _inline

        response = _inline(opened)
        response["Content-Length"] = len(opened["raw"])
        response["Accept-Ranges"] = "none"
        if request.method == "HEAD":
            response.content = b""

        return private(response)
    except (cases.CaseConflict, IdentityUnavailable):
        return denied("pdf_unavailable", 404)
    except (DatabaseError, SyntheticWriteDenied):
        return denied("pdf_unavailable", 503)


def review_document(request, citation_id):
    return document(request, citation_id, review=True)
