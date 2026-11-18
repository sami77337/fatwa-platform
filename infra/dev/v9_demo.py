"""Opt-in V9 manual demo, reusing V8 bootstrap on a fresh owned synthetic database.

Run with infra/dev/with_casework_postgres.py. No signing key, approval, provider
sender, browser credential endpoint or production configuration is created here.
"""

import argparse
import io
import json
import os
import re
import sys
import tempfile
from contextlib import ExitStack, redirect_stdout
from html import unescape
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode


def _public_key(path):
    with Path(path).open("rb") as key_file:
        raw = key_file.read(33)
    if len(raw) != 32:
        raise ValueError("expected a raw 32-byte synthetic Ed25519 public key")
    return raw


def _approval_verifier(public_key, directory, case_ref):
    """An optional external authority's PUBLIC key only; never sign in the app."""
    from apps.delivery_planner.trusted_identity import Ed25519ApprovalVerifier, IdentityStatus
    from apps.mufti_review.identity import IdentityUnavailable, resolve_identity

    raw = _public_key(public_key)

    def identity(subject):
        if subject != "demo-mufti":
            return None
        try:
            actor = resolve_identity(directory, subject, case_key=case_ref)
            return IdentityStatus(actor.subject_id, actor.role, actor.active)
        except IdentityUnavailable:
            return None

    return Ed25519ApprovalVerifier(
        issuer="synthetic-v9-offline-authority",
        audience="synthetic-v9-composite",
        trusted_public_keys={"demo-public-key": raw},
        identity_lookup=identity,
        # This ephemeral manual authority has no separate revocation administration.
        # Canonical current approval/identity and durable queue nonce binding remain enforced.
        is_revoked_or_consumed=lambda *_: False,
    )


def _configure(scope, *, public_key=None, provider_public_key=None):
    from django.conf import settings
    from django.utils import timezone

    from apps.composite_delivery.services import SIMULATOR_PROVIDER, ChannelProfile
    from apps.delivery_planner.planner import Capabilities
    from apps.knowledge_links.authority import KnowledgeAuthority

    directory = settings.FATWA_CASEWORK_IDENTITY_PROVIDER

    class Authority(KnowledgeAuthority):
        def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, kind):
            actor = directory.resolve(subject_id)
            return bool(
                actor
                and actor.active
                and actor.valid_until > timezone.now()
                and actor.role == "MUFTI"
                and actor.auth_epoch == auth_epoch
                and provider_id == directory.provider_id
                and subject_id == "demo-publisher"
                and case_ref in scope
                and case_ref in actor.case_keys
                and kind == "REFERENCE"
                and action in {"APPROVE", "WITHDRAW"}
            )

    settings.FATWA_KNOWLEDGE_LINKS_ENABLED = True
    settings.FATWA_KNOWLEDGE_LINKS_AUTHORITY = Authority()
    settings.FATWA_COMPOSITE_DELIVERY_ENABLED = True
    profile = ChannelProfile(
        Capabilities(
            SIMULATOR_PROVIDER,
            "synthetic.v9.demo",
            frozenset({"text", "document", "audio", "image"}),
            6000,
            True,
        ),
        192000,
        frozenset(
            {
                "text/plain",
                "application/pdf",
                "image/jpeg",
                "image/png",
                "image/webp",
                "audio/mpeg",
                "audio/mp4",
                "audio/wav",
            }
        ),
    )
    # A declared offline fixture profile; it makes no claim about a live channel.
    settings.FATWA_COMPOSITE_DELIVERY_CAPABILITIES = lambda source: (
        profile if source == "website" else None
    )
    if public_key:
        settings.FATWA_CASE_DELIVERY_APPROVAL_VERIFIER = _approval_verifier(
            public_key, directory, next(iter(scope))
        )
    # No worker, provider signing authority or sender is installed.
    settings.FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER = None
    if provider_public_key:
        from apps.delivery_queue.signed_provider_receipts import Ed25519ProviderEventVerifier

        settings.FATWA_COMPOSITE_DELIVERY_PROVIDER_VERIFIER = Ed25519ProviderEventVerifier(
            issuer="synthetic-v9-offline-provider",
            audience="synthetic-v9-provider-events",
            provider=SIMULATOR_PROVIDER,
            trusted_public_keys={"demo-provider-key": _public_key(provider_public_key)},
        )


def _smoke(receipt, output, source_raw, storage):
    """Small startup check with actual sessions/CSRF and one fabricated file; no approvals."""
    from django.conf import settings
    from django.test import Client

    from apps.case_attachments import services as attachments
    from apps.case_attachments.models import CaseAttachment
    from apps.casework.models import AnswerRevision, Case, CaseDecision
    from apps.delivery_queue.models import DeliveryIntent
    from apps.reference.models import ReferenceHeading
    from apps.source_case_intake.models import SourceReceipt

    def require(value, label):
        if not value:
            raise RuntimeError("V9 demo smoke failed: " + label)

    def post(client, path, fields, page):
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
        require(token, "csrf form")
        return client.post(
            path,
            urlencode({"csrfmiddlewaretoken": unescape(token[1]), **fields}),
            content_type="application/x-www-form-urlencoded",
        )

    def make_client():
        return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    requester, staff = make_client(), make_client()
    page = requester.get("/casework/status/")
    require(page.status_code == 200, "requester entry")
    result = post(
        requester, "/casework/status/", {"action": "unlock", "token": receipt["token"]}, page
    )
    require(result.status_code == 303, "requester capability")
    require(requester.get("/casework/status/").status_code == 200, "requester workspace")
    credential = next(
        line.split(": ", 1)[1]
        for line in output.splitlines()
        if line.startswith("demo-mufti temporary credential: ")
    )
    page = staff.get("/casework/staff/login/")
    require(
        post(staff, "/casework/staff/login/", {"credential": credential}, page).status_code == 303,
        "staff login",
    )
    page = staff.get("/casework/staff/")
    case_page = post(
        staff, "/casework/staff/", {"action": "open", "case_ref": receipt["public_ref"]}, page
    )
    require(
        case_page.status_code == 200 and "أصل رسائل القضية" in case_page.content.decode(),
        "scoped source provenance UI",
    )
    require(
        Case.objects.count() == 1 and bytes(SourceReceipt.objects.get().raw) == source_raw,
        "one canonical raw source",
    )
    require(ReferenceHeading.objects.count() == 2, "inherited V8 reference fixtures")
    payload = b"Synthetic V9 demo storage smoke only.\n"
    row = attachments.upload(
        token=receipt["token"],
        raw=payload,
        filename="demo-smoke.txt",
        media_type="text/plain",
        expected_revision=1,
        synthetic_fixtures_only=True,
    )
    owner = CaseAttachment.objects.get(pk=row["id"])
    require(
        owner.original is None and owner.storage_backend == "private-filesystem-v1",
        "external original binding",
    )
    directory = settings.FATWA_CASEWORK_IDENTITY_PROVIDER
    authority = settings.FATWA_KNOWLEDGE_LINKS_AUTHORITY
    approval_context = {
        "provider_id": directory.provider_id,
        "auth_epoch": "demo-epoch",
        "case_ref": receipt["public_ref"],
        "action": "APPROVE",
        "kind": "REFERENCE",
    }
    require(
        authority.permits(subject_id="demo-publisher", **approval_context) is True,
        "independent reference reviewer configured",
    )
    require(
        authority.permits(subject_id="demo-mufti", **approval_context) is False,
        "reference proposer has no independent review grant",
    )
    read = attachments.staff_read(
        case_id=receipt["case_id"],
        subject_id="demo-mufti",
        provider=directory,
        attachment_id=owner.pk,
        synthetic_fixtures_only=True,
    )
    require(
        read["raw"] == payload and (storage.root / "objects" / owner.storage_key).is_file(),
        "exact authorized original read",
    )
    require(
        not AnswerRevision.objects.exists()
        and not CaseDecision.objects.exists()
        and not DeliveryIntent.objects.exists(),
        "no automatic answer approval or transport",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "synthetic_only": True,
                "source_cases": 1,
                "reference_locations": 2,
                "requester_and_staff_csrf_sessions": True,
                "private_filesystem_roundtrip": True,
                "automatic_approvals": 0,
                "delivery_intents": 0,
                "external_send": False,
            },
            sort_keys=True,
        )
    )


def _startup_notice(args):
    """Presentation-only bootstrap hook; later closed demos describe their own mode."""
    print("Composite plan export/import enabled; no sender, provider outcomes or automatic approval.")
    print(
        "Signed staging:",
        "external PUBLIC-key verification enabled"
        if args.approval_public_key
        else "closed until both external public verification keys are supplied; export remains available",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Check startup and private file roundtrip, then exit; no approvals or server.",
    )
    parser.add_argument(
        "--approval-public-key",
        type=Path,
        help="Optional raw 32-byte PUBLIC key of an independent synthetic offline authority; no private key accepted.",
    )
    parser.add_argument(
        "--provider-public-key",
        type=Path,
        help="Optional raw 32-byte PUBLIC key for independent synthetic provider event verification; requires --approval-public-key.",
    )
    args = parser.parse_args(argv)
    if bool(args.approval_public_key) != bool(args.provider_public_key):
        parser.error("provide both public verification keys, or neither for export-only mode")
    if os.environ.get("FATWA_PRODUCTION") != "0":
        raise RuntimeError("run through the owned synthetic PostgreSQL helper")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.campaign_review")
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    from apps.casework import services as cases
    from apps.intake_workflow.guards import require_owned_database
    from apps.private_media.filesystem import FileSystemStorage
    from apps.requester_team_journey.v7_demo import main as v8_runtime
    from apps.source_case_intake import services as origins
    from apps.source_case_intake import simulators

    require_owned_database(synthetic_fixtures_only=True)
    source_raw = simulators.website()
    original_intake = cases.intake_case
    receipt = None
    real_stdout = sys.stdout
    captured = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="fatwa-v9-demo-") as temporary:
        storage = FileSystemStorage(Path(temporary), synthetic_fixtures_only=True)
        settings.FATWA_PRIVATE_MEDIA_STORAGE = storage
        settings.FATWA_SOURCE_CASE_INTAKE_ENABLED = True

        def seed_from_source(**kwargs):
            nonlocal receipt
            if kwargs.get("source_event_id", "").startswith("v7-demo:"):
                if receipt is not None:
                    raise RuntimeError("demo seed must be created exactly once")
                receipt = origins.ingest(
                    raw=source_raw,
                    context=simulators.context("website"),
                    synthetic_fixtures_only=True,
                )
                return receipt
            # Source intake calls the original canonical service with its source: event.
            return original_intake(**kwargs)

        with ExitStack() as boot:

            def start(command, *command_args, **command_kwargs):
                if command != "runserver":
                    return call_command(command, *command_args, **command_kwargs)
                if receipt is None:
                    raise RuntimeError("source seed missing")
                output = captured.getvalue()
                # Hooks are bootstrap-only: ordinary request handling uses original functions.
                boot.close()
                _configure(
                    frozenset({receipt["public_ref"]}),
                    public_key=args.approval_public_key,
                    provider_public_key=args.provider_public_key,
                )
                if args.smoke:
                    return _smoke(receipt, output, source_raw, storage)
                print(output, end="", file=real_stdout)
                print(
                    "V9: one canonical website source receipt; original payload retained with its hash."
                )
                print("Private synthetic filesystem (deleted on exit):", storage.root)
                print(
                    "Knowledge review: demo-mufti proposes a cited REFERENCE; demo-publisher independently approves it."
                )
                _startup_notice(args)
                print("Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.", flush=True)
                return call_command(command, *command_args, **command_kwargs)

            boot.enter_context(patch.object(cases, "intake_case", seed_from_source))
            boot.enter_context(patch("django.core.management.call_command", start))
            boot.enter_context(redirect_stdout(captured))
            v8_runtime(multipart=True)


if __name__ == "__main__":
    main()
