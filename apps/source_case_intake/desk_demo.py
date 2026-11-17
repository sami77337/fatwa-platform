"""Start the source desk on loopback inside the repository's owned PostgreSQL helper."""

import argparse
import secrets
import tempfile
from datetime import timedelta
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke", action="store_true", help="Build synthetic fixtures and check, without serving."
    )
    args = parser.parse_args(argv)
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.utils import timezone

    from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider

    from . import services, simulators
    from .desk_services import inbox

    settings.FATWA_CASEWORK_WEB_ENABLED = True
    settings.FATWA_SOURCE_CASE_INTAKE_ENABLED = True
    settings.FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED = True
    settings.FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED = True
    settings.FATWA_CASE_ATTACHMENTS_ENABLED = True
    settings.ROOT_URLCONF = "apps.source_case_intake.urls"
    roots = []
    for source in ("telegram", "youtube", "website"):
        fixture = getattr(simulators, source)
        raw = fixture(document=True) if source == "telegram" else fixture()
        roots.append(
            services.ingest(
                raw=raw, context=simulators.context(source), synthetic_fixtures_only=True
            )
        )
    for raw in (simulators.telegram(2, parent=1), simulators.telegram(3, sender=200, parent=1)):
        services.ingest(
            raw=raw, context=simulators.context("telegram"), synthetic_fixtures_only=True
        )
    services.capture(
        raw=simulators.telegram(4, parent=999),
        context=simulators.context("telegram"),
        synthetic_fixtures_only=True,
    )
    credential = secrets.token_urlsafe(40)
    identity = MuftiIdentity(
        "source-demo-mufti",
        "MUFTI",
        True,
        frozenset({services.REVIEW_SCOPE, *(r["public_ref"] for r in roots)}),
        "source-demo-epoch",
        timezone.now() + timedelta(minutes=45),
    )

    class DemoDirectory(MuftiIdentityProvider):
        provider_id = "synthetic-source-desk-demo"

        def authenticate(self, value):
            return identity if value == credential else None

        def resolve(self, subject_id):
            return identity if subject_id == identity.subject_id else None

    settings.FATWA_CASEWORK_IDENTITY_PROVIDER = DemoDirectory()
    call_command("check")
    if args.smoke:
        result = inbox(
            subject_id=identity.subject_id,
            provider=settings.FATWA_CASEWORK_IDENTITY_PROVIDER,
            synthetic_fixtures_only=True,
        )
        if len(result["receipts"]) != 6:
            raise RuntimeError("unexpected_demo_receipts")
        print(
            "SOURCE_DESK_DEMO_PASS: 3 source cases, 2 review tickets, 1 pending receipt; no approvals/sends"
        )
        return
    with tempfile.TemporaryDirectory(prefix="source-desk-synthetic-") as directory:
        sample = Path(directory) / "synthetic.txt"
        sample.write_text("مرفق اصطناعي لتجربة مكتب المصادر فقط.\n")
        print("Synthetic-only source desk: http://127.0.0.1:8020/casework/staff/login/", flush=True)
        print("45-minute synthetic MUFTI credential:", credential, flush=True)
        print("Telegram case capability for followup/file forms:", roots[0]["token"], flush=True)
        print("Synthetic attachment:", sample, flush=True)
        print(
            "New split cases do not automatically grant staff access; use the existing recovery/scope workflow.",
            flush=True,
        )
        call_command("runserver", "127.0.0.1:8020", use_reloader=False)


if __name__ == "__main__":
    main()
