"""Explicit synthetic local demo; test signer stays outside application code."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8018)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("use a local unprivileged port")
    if os.environ.get("DJANGO_SETTINGS_MODULE") != "apps.case_delivery_desk.settings":
        parser.error("use the explicit delivery desk profile")
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.test import Client

    from apps.casework.models import Case
    from apps.intake_workflow.guards import require_synthetic_write
    from tests.casework.test_http import post

    from .fixtures import CREDENTIAL, DeskFixture

    require_synthetic_write(synthetic_fixtures_only=True)
    if not settings.FATWA_CASEWORK_WEB_ENABLED or Case.objects.exists():
        parser.error("enable the local desk and use a fresh owned empty case database")

    class Demo(DeskFixture):
        def addCleanup(self, function):
            self.cleanup.append(function)

    fixture = Demo()
    fixture.cleanup = []
    try:
        fixture.setUp()
        first = fixture.a
        response = fixture.signed_response()
        for suffix in ("demo-awaiting", "demo-delivered"):
            case = fixture.intake(suffix)
            fixture.directory.refs |= frozenset({case["public_ref"]})
            fixture.approve(case)
            fixture.stage(case)
            if suffix == "demo-awaiting":
                fixture.reserve(case)
            else:
                fixture.deliver(case)
        output = Path(".local/qa/case-delivery-desk/demo-response.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        # Short-lived, synthetic signed response only; never export either test key.
        with os.fdopen(
            os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
        ) as stream:
            stream.write(response)
        if args.check:
            client = Client(
                enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
            )
            page = client.get("/casework/staff/login/")
            assert (
                post(client, "/casework/staff/login/", {"credential": CREDENTIAL}, page).status_code
                == 303
            )
            page = client.get("/casework/staff/")
            assert page.status_code == 200 and first["public_ref"] in page.content.decode()
            assert fixture.foreign["public_ref"] not in page.content.decode()
            print("DELIVERY_DESK_DEMO=PASS; 3 scoped cases and 1 hidden case; synthetic only")
            return
        print(f"Local desk: http://127.0.0.1:{args.port}/casework/staff/login/", flush=True)
        print(f"Synthetic credential: {CREDENTIAL}", flush=True)
        print(
            f"First case: {first['public_ref']}; select 24 characters and explicit splitting.",
            flush=True,
        )
        print(
            f"Synthetic signed response: {output}; valid for four minutes from startup.", flush=True
        )
        print(
            "Second case: reserved attempt expires after 60 seconds. Third: signed provider delivery.",
            flush=True,
        )
        call_command("runserver", f"127.0.0.1:{args.port}", use_reloader=False)
    finally:
        for cleanup in reversed(fixture.cleanup):
            cleanup()


if __name__ == "__main__":
    main()
