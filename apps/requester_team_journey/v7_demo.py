"""Manual V7 demo: fresh owned synthetic PostgreSQL only, never production."""

import os
import secrets
from datetime import timedelta
from pathlib import Path


def main(*, multipart=False):
    if os.environ.get("FATWA_PRODUCTION") != "0":
        raise RuntimeError("synthetic profile required")
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.campaign_review"
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.utils import timezone

    from apps.casework.models import Case
    from apps.casework.services import intake_case
    from apps.experimental_publication.authority import PublicationAuthority
    from apps.intake_workflow.guards import require_owned_database
    from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider
    from apps.reference.ingest import ingest_catalog
    from apps.reference.records import CatalogSpec, HeadingRecord

    require_owned_database(synthetic_fixtures_only=True)
    if Case.objects.exists():
        raise RuntimeError("demo requires a fresh empty synthetic database")
    spec = CatalogSpec(
        source_namespace="synthetic-v7",
        source_book_id="622",
        work_title="مرجع تجريبي مختلق",
        madhhab="اختبار فقط",
        edition_key="v7-synthetic",
        edition_title="طبعة اصطناعية",
        publisher="ناشر مختلق",
        source_archive_sha256="a" * 64,
        source_input_sha256="b" * 64,
        input_name="synthetic-v7-demo",
        expected_rows=2 if multipart else 1,
        expected_roots=2 if multipart else 1,
        expected_max_depth=1,
    )
    rows = (HeadingRecord("v7-demo-1", 1, None, 1, 1, 1, 1, "1", 1, "باب تجريبي"),)
    if multipart:
        rows += (HeadingRecord("v8-demo-2", 2, None, 2, 2, 1, 2, "2", 2, "باب تجريبي ثان"),)
    preview = ingest_catalog(spec, rows)
    ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum)
    key = secrets.token_hex(16)
    receipt = intake_case(
        original_question="سؤال اصطناعي لتجربة المرفقات والإحالات والنشر المغلق.",
        source_event_id="v7-demo:" + key,
        requester_id="v7-demo:" + key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    credentials = {name: secrets.token_urlsafe(48) for name in ("demo-mufti", "demo-publisher")}
    expires = timezone.now() + timedelta(minutes=45)
    scope = frozenset({receipt["public_ref"]})

    class Directory(MuftiIdentityProvider):
        provider_id = "synthetic-v7-demo"

        def resolve(self, subject_id):
            if subject_id not in credentials:
                return None
            return MuftiIdentity(subject_id, "MUFTI", True, scope, "demo-epoch", expires)

        def authenticate(self, credential):
            return next(
                (
                    self.resolve(name)
                    for name, value in credentials.items()
                    if secrets.compare_digest(value, credential)
                ),
                None,
            )

    class Authority(PublicationAuthority):
        def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
            return (
                provider_id == "synthetic-v7-demo"
                and subject_id == "demo-publisher"
                and auth_epoch == "demo-epoch"
                and case_ref in scope
                and action in {"APPROVE", "WITHDRAW"}
                and timezone.now() < expires
            )

    settings.FATWA_CASEWORK_WEB_ENABLED = True
    settings.FATWA_CASEWORK_IDENTITY_PROVIDER = Directory()
    settings.FATWA_CASE_ATTACHMENTS_ENABLED = True
    settings.FATWA_CASE_CITATIONS_ENABLED = True
    settings.FATWA_EXPERIMENTAL_PUBLICATION_ENABLED = True
    settings.FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY = Authority()
    if multipart:
        settings.FATWA_ANSWER_MEDIA_ENABLED = True
        settings.FATWA_ANSWER_MEDIA_PRIVATE_ENABLED = True
        from apps.private_media.fixtures import synthetic_files

        output = Path(".local/qa/v8/samples")
        output.mkdir(parents=True, exist_ok=True)
        for filename, _, raw in synthetic_files():
            (output / filename).write_bytes(raw)
        print("Synthetic image/PDF/audio/text samples:", output)
    sample = Path(".local/qa/v7/sample.txt")
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text("وقائع اصطناعية إضافية لاستخدام تجربة V7 فقط.\n")
    print("Synthetic only; expires after 45 minutes; server binds loopback only.")
    port = 8018 if multipart else 8017
    print(f"Requester: http://127.0.0.1:{port}/casework/status/")
    print("One-case requester capability:", receipt["token"])
    print("Case:", receipt["public_ref"])
    print(f"Staff login: http://127.0.0.1:{port}/casework/staff/login/")
    for subject, credential in credentials.items():
        print(subject, "temporary credential:", credential)
    print("Synthetic upload:", sample)
    print(
        "No delivery signer or recovery authority configured. Browser test covers signed delivery."
    )
    if multipart:
        print(
            "Multipart private availability requires separate explicit human release; no provider delivery."
        )
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False)


if __name__ == "__main__":
    main()
