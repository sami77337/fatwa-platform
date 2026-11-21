"""Explicit synthetic identity and policy; no MFA or production account assurance."""

import uuid
from datetime import timedelta

from django.test import Client, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework_web import access
from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider
from tests.casework import test_http as http

from .authority import FreshAuthentication, FreshResult, ReauthenticationRule, SessionAuthority

FEATURES = {
    **http.WEB_SETTINGS,
    "ROOT_URLCONF": "apps.staff_sessions.test_urls",
    "MIDDLEWARE": [
        "apps.staff_sessions.middleware.SessionContext",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
    "FATWA_STAFF_SESSIONS_ENABLED": True,
    "FATWA_STAFF_SESSION_RUNTIME_EPOCH": "synthetic-session-runtime-generation-0001",
}
CREDENTIALS = {
    name: "synthetic-session-" + name + "-credential-32-characters"
    for name in ("mufti", "other", "admin")
}


class Directory(FreshAuthentication, MuftiIdentityProvider):
    provider_id = "synthetic-session-directory"
    fresh_method_id = "SYNTHETIC-current-credential.v1"

    def __init__(self, ref):
        self.identities = {
            name: MuftiIdentity(
                name,
                role,
                True,
                frozenset({ref}),
                "epoch-1",
                timezone.now() + timedelta(minutes=30),
            )
            for name, role in (("mufti", "MUFTI"), ("other", "MUFTI"), ("admin", "ORGANIZER_ADMIN"))
        }
        self.hook = None
        self.calls = []

    def projection_epoch(self):
        return repr(
            (self.provider_id, sorted((key, repr(actor)) for key, actor in self.identities.items()))
        )

    def resolve(self, subject_id):
        return self.identities.get(subject_id)

    def authenticate(self, credential):
        self.calls.append("authenticate")
        return self.resolve(
            next((key for key, value in CREDENTIALS.items() if value == credential), "")
        )

    def authenticate_fresh(self, credential, *, challenge):
        actor = self.authenticate(credential)
        try:
            if self.hook:
                self.hook()
            return FreshResult(actor, challenge, timezone.now(), self.fresh_method_id)
        finally:
            from threading import current_thread

            from django.db import connections

            if current_thread().name == "fatwa-session-fresh-verifier":
                connections.close_all()


class Authority(SessionAuthority):
    def __init__(self):
        self.denied = set()
        self.admin_targets = set()
        self.until = timezone.now() + timedelta(minutes=30)
        self.fresh_seconds = 90
        self.required = True
        self.hook = None

    def projection_epoch(self):
        return repr(
            (
                sorted(self.denied),
                sorted(self.admin_targets),
                self.until.isoformat(),
                self.fresh_seconds,
                self.required,
            )
        )

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        r = values["resource"]
        return (
            values["provider_id"] == Directory.provider_id
            and values["subject_id"] in {"mufti", "other", "admin"}
            and values["auth_epoch"] == "epoch-1"
            and values["role"]
            == ("ORGANIZER_ADMIN" if values["subject_id"] == "admin" else "MUFTI")
            and values["action"] in {"ISSUE", "USE", "LIST", "READ", "REVOKE", "LOGOUT", "AUDIT"}
            and values["action"] not in self.denied
            and r["provider_id"] == Directory.provider_id
            and r["surface"] in {"CASEWORK", "OPERATIONS"}
            and (
                r["subject_id"] == values["subject_id"]
                or (values["subject_id"] == "admin" and r.get("id") in self.admin_targets)
            )
            and timezone.now() < self.until
        )

    def reauthentication(self, **values):
        return ReauthenticationRule(self.required, self.fresh_seconds)


class SessionFixture:
    def setUp(self):
        super().setUp()
        key = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="أصل السؤال  محفوظ حرفيًا.\n",
            source_event_id=key,
            requester_id=key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        self.directory = Directory(self.receipt["public_ref"])
        self.authority = Authority()
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_STAFF_SESSION_AUTHORITY=self.authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        common = dict(
            case_id=self.receipt["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        saved = cases.save_answer(
            **common,
            text="جواب بشري اصطناعي  محفوظ.\n",
            expected_revision=1,
            expected_evidence_version=1,
        )
        cases.record_decision(
            **common,
            answer_id=saved["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.client, self.page = self.login()
        self.other_client, self.other_page = self.login()

    def login(self, subject="mufti"):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        response = http.post(
            client, "/casework/staff/login/", {"credential": CREDENTIALS[subject]}, page
        )
        self.assertEqual(response.status_code, 303, response.content)
        page = client.get("/casework/sessions/")
        self.assertEqual(page.status_code, 200, page.content)
        return client, page

    def session_id(self, client):
        import json

        from django.http import HttpRequest

        request = HttpRequest()
        request.COOKIES = {key: value.value for key, value in client.cookies.items()}
        return json.loads(request.get_signed_cookie(access.COOKIE, salt=access.SALT))["session_id"]

    def select(self, client=None, target=None):
        client = client or self.client
        page = client.get("/casework/sessions/")
        return http.post(
            client,
            "/casework/sessions/",
            {"action": "select", "target_id": target or self.session_id(self.other_client)},
            page,
        )

    def fresh(self, page=None, credential=None, client=None):
        page = page or self.select(client)
        return http.post(
            client or self.client,
            "/casework/sessions/",
            {
                "action": "reauthenticate",
                "target_id": http.hidden(page, "target_id"),
                "ticket": http.hidden(page, "ticket"),
                "credential": credential or CREDENTIALS["mufti"],
            },
            page,
        )

    def revoke(self, page, client=None):
        return http.post(
            client or self.client,
            "/casework/sessions/",
            {
                "action": "revoke",
                "target_id": http.hidden(page, "target_id"),
                "ticket": http.hidden(page, "ticket"),
                "proof_id": http.hidden(page, "proof_id"),
            },
            page,
        )


def operational_authority(receipt):
    from apps.operational_workspace.authority import OperationalAuthority as Base

    class Exact(Base):
        def projection_epoch(self):
            return "synthetic-admin-single-case-read-v1"

        def permits(self, **values):
            return (
                values["provider_id"] == Directory.provider_id
                and values["subject_id"] == "admin"
                and values["role"] == "ORGANIZER_ADMIN"
                and values["auth_epoch"] == "epoch-1"
                and values["case_ref"] == receipt["public_ref"]
                and values["action"]
                in {
                    "READ_QUEUE",
                    "READ_CASE",
                    "READ_METADATA",
                    "READ_DELIVERY",
                    "READ_PUBLICATION",
                    "READ_TRANSCRIPT",
                    "READ_CAPABILITY",
                }
                and values["resource"].get("case_id") == receipt["case_id"]
            )

        def grant_deadline(self, **values):
            return timezone.now() + timedelta(minutes=5) if self.permits(**values) else None

    return Exact()
