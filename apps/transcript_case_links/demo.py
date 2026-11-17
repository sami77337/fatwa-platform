"""Launch only inside an explicitly owned synthetic database (see README)."""

import os
import secrets
from datetime import timedelta


def main():
    if os.environ.get("FATWA_PRODUCTION") != "0":
        raise RuntimeError("synthetic profile required")
    os.environ["FATWA_CASEWORK_WEB_ENABLED"] = "1"
    os.environ["DJANGO_SETTINGS_MODULE"] = "apps.transcript_case_links.settings"
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.utils import timezone

    from apps.casework.services import intake_case
    from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider

    key = secrets.token_hex(16)
    receipt = intake_case(
        original_question="سؤال موقع مختلق لتجربة ربط التفريغ فقط.",
        source_event_id="demo:" + key,
        requester_id="demo:" + key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    credential = secrets.token_urlsafe(48)
    identity = MuftiIdentity(
        "synthetic-transcript-reviewer",
        "MUFTI",
        True,
        frozenset({receipt["public_ref"]}),
        "demo-epoch",
        timezone.now() + timedelta(minutes=45),
    )

    class DemoDirectory(MuftiIdentityProvider):
        provider_id = "synthetic-transcript-demo"

        def resolve(self, subject_id):
            return identity if subject_id == identity.subject_id else None

        def authenticate(self, supplied):
            return identity if secrets.compare_digest(supplied, credential) else None

    settings.FATWA_CASEWORK_IDENTITY_PROVIDER = DemoDirectory()
    settings.FATWA_CASEWORK_WEB_ENABLED = True
    print("Local synthetic login: http://127.0.0.1:8018/casework/staff/login/")
    print("Temporary synthetic credential (45 minutes):", credential)
    print("Scoped synthetic case:", receipt["public_ref"])
    call_command("runserver", "127.0.0.1:8018", use_reloader=False)


if __name__ == "__main__":
    main()
