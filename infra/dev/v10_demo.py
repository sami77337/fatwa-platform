"""V10 manual demonstration reusing the V9 owned synthetic runtime.

Only V9 bootstrap extension points are wrapped. Domain services, authentication,
case records, transactions and the application URL configuration are not replaced.
"""

import argparse
import json
import re
import sys
import tempfile
from dataclasses import replace
from html import unescape
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from infra.dev import v9_demo


def _source_reviewer(directory):
    """Only the seeded primary MUFTI receives the explicit source-review queue scope."""
    from apps.mufti_review.identity import MuftiIdentityProvider
    from apps.source_case_intake.services import REVIEW_SCOPE

    class Directory(MuftiIdentityProvider):
        provider_id = directory.provider_id

        def resolve(self, subject_id):
            actor = directory.resolve(subject_id)
            if actor is not None and subject_id == "demo-mufti":
                return replace(actor, case_keys=actor.case_keys | frozenset({REVIEW_SCOPE}))
            return actor

        def authenticate(self, credential):
            actor = directory.authenticate(credential)
            return self.resolve(actor.subject_id) if actor else None

    return Directory()


def _held_source_event():
    """Queue an ambiguous same-origin event for a human; never resolve or approve it."""
    from apps.casework.models import Case
    from apps.source_case_intake import services, simulators

    before = Case.objects.values("id", "revision", "evidence_version", "answer_revision").get()
    payload = json.loads(simulators.website(2))
    payload["text"] = "تعقيب اصطناعي مستقل ينتظر مراجعة الربط البشري؛ لا يغيّر الوقائع قبل المراجعة."
    result = services.ingest(
        raw=simulators.raw(payload),
        context=simulators.context("website"),
        synthetic_fixtures_only=True,
    )
    after = Case.objects.values("id", "revision", "evidence_version", "answer_revision").get()
    if result["status"] != "NEEDS_REVIEW" or before != after:
        raise RuntimeError("V10 demo requires a held source event without a case/evidence mutation")
    return result


def _check_source_desk(receipt, output, held):
    """Read the new queue through real staff sessions; do not resolve the held event."""
    from django.conf import settings
    from django.test import Client

    from apps.casework.models import CaseDecision
    from apps.delivery_queue.models import DeliveryIntent
    from apps.source_case_intake.models import EvidenceBinding
    from apps.source_case_intake.services import REVIEW_SCOPE

    directory = settings.FATWA_CASEWORK_IDENTITY_PROVIDER
    if REVIEW_SCOPE not in directory.resolve("demo-mufti").case_keys:
        raise RuntimeError("V10 demo primary source reviewer missing")
    if REVIEW_SCOPE in directory.resolve("demo-publisher").case_keys:
        raise RuntimeError("V10 demo publisher must not receive the source review scope")
    credential = next(
        line.split(": ", 1)[1]
        for line in output.splitlines()
        if line.startswith("demo-mufti temporary credential: ")
    )
    client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def post(fields, page, path="/casework/staff/"):
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
        if match is None:
            raise RuntimeError("V10 demo staff CSRF form missing")
        return client.post(
            path,
            urlencode({"csrfmiddlewaretoken": unescape(match[1]), **fields}),
            content_type="application/x-www-form-urlencoded",
        )

    login = client.get("/casework/staff/login/")
    if post({"credential": credential}, login, "/casework/staff/login/").status_code != 303:
        raise RuntimeError("V10 demo staff login failed")
    desk = client.get("/casework/staff/")
    overview = post({"action": "case_workspace", "case_ref": receipt["public_ref"]}, desk)
    if overview.status_code != 200 or 'id="mufti-work-heading"' not in overview.content.decode():
        raise RuntimeError("V10 demo connected Mufti overview unavailable")
    inbox = post({"action": "source_inbox"}, desk)
    if inbox.status_code != 200 or held["receipt_id"] not in inbox.content.decode():
        raise RuntimeError("V10 demo held event absent from source desk")
    if EvidenceBinding.objects.filter(receipt_id=held["receipt_id"]).exists():
        raise RuntimeError("V10 demo must not resolve source correlation automatically")
    if CaseDecision.objects.exists() or DeliveryIntent.objects.exists():
        raise RuntimeError("V10 demo must not create approval or delivery intent")
    print(
        json.dumps(
            {
                "v10_source_desk": "PASS",
                "primary_mufti_only": True,
                "held_source_events": 1,
                "automatic_correlation": False,
                "anonymous_preview_granted": False,
            },
            sort_keys=True,
        )
    )


def _recovery_smoke(storage, pg_bin):
    """No HTTP server/worker/GC starts in this mode; source lifetime still encloses this drill."""
    from apps.platform_recovery.service import restore, snapshot, verify_bundle

    with tempfile.TemporaryDirectory(prefix="fatwa-v10-recovery-", dir="/tmp") as scratch:
        backup = snapshot(
            scratch=Path(scratch),
            storage=storage,
            pg_bin=pg_bin,
            synthetic_fixtures_only=True,
            offline=True,
        )
        # Keep the trusted digest separately in memory; never trust an archive's own replacement pin.
        pin = backup["manifest_sha256"]
        verify_bundle(backup["bundle"], pin)
        recovered = restore(
            bundle=backup["bundle"],
            expected_manifest_sha256=pin,
            scratch=Path(scratch),
            pg_bin=pg_bin,
            synthetic_fixtures_only=True,
            offline=True,
        )
        if recovered["state"] != "READY":
            raise RuntimeError("V10 recovery smoke did not produce a verified READY target")
        print(
            json.dumps(
                {
                    "v10_recovery": "READY",
                    "tables": backup["tables"],
                    "external_assets": backup["assets"],
                    "source_unchanged": True,
                    "cutover": False,
                    "runtime_authority_reattached": False,
                    "temporary_drill_only": True,
                },
                sort_keys=True,
            )
        )
        # No application switches to this database. The enclosing helper destroys its
        # exclusively owned cluster on exit; this scratch context removes drill files.


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument(
        "--smoke-recovery",
        action="store_true",
        help="Run smoke then offline snapshot/verify/restore before temporary cleanup; never serve HTTP.",
    )
    parser.add_argument(
        "--recovery-pg-bin",
        type=Path,
        help="Matching PostgreSQL pg_dump/pg_restore directory; required with --smoke-recovery.",
    )
    recovery, arguments = parser.parse_known_args(arguments)
    if "--help" in arguments or "-h" in arguments:
        parser.print_help()
        return v9_demo.main(arguments)
    if recovery.smoke_recovery != bool(recovery.recovery_pg_bin):
        parser.error("--smoke-recovery requires --recovery-pg-bin, and conversely")
    if recovery.smoke_recovery and "--smoke" not in arguments:
        arguments.append("--smoke")
    smoke = "--smoke" in arguments
    configure_v9, smoke_v9 = v9_demo._configure, v9_demo._smoke
    held = None

    def configure(scope, **options):
        nonlocal held
        from django.conf import settings

        configure_v9(scope, **options)
        settings.FATWA_MUFTI_WORKSPACE_ENABLED = True
        settings.FATWA_REQUESTER_PORTAL_ENABLED = True
        settings.FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED = True
        settings.FATWA_CASEWORK_IDENTITY_PROVIDER = _source_reviewer(
            settings.FATWA_CASEWORK_IDENTITY_PROVIDER
        )
        settings.FATWA_LIBRARY_PREVIEW_ENABLED = False
        settings.FATWA_LIBRARY_PREVIEW_POLICY = None
        if not smoke:
            held = _held_source_event()
            print("V10: one additional source event awaits explicit human correlation review.")
            print("No automatic answer, approval, publication, recovery or delivery action.")

    def check(receipt, output, source_raw, storage):
        nonlocal held
        from django.test import override_settings

        # V9's baseline asserts its legacy presentation. Test it under its own switch,
        # then separately assert the connected V10 overview below with A re-enabled.
        with override_settings(FATWA_MUFTI_WORKSPACE_ENABLED=False):
            smoke_v9(receipt, output, source_raw, storage)
        held = _held_source_event()
        _check_source_desk(receipt, output, held)
        if recovery.smoke_recovery:
            _recovery_smoke(storage, recovery.recovery_pg_bin)

    with patch.object(v9_demo, "_configure", configure), patch.object(v9_demo, "_smoke", check):
        v9_demo.main(arguments)


if __name__ == "__main__":
    main()
