"""Real password/TOTP algorithms on fabricated accounts; no production provider."""

import base64
from datetime import timedelta

from cryptography.fernet import Fernet
from django.contrib.auth.hashers import check_password, make_password
from django.test import override_settings
from django.utils import timezone

from apps.case_attachments.tests import new_case
from apps.staff_sessions import integration as session_context
from apps.staff_sessions import services as sessions
from apps.staff_sessions.test_support import Authority as BaseSessionAuthority
from apps.staff_sessions.test_support import Directory as SessionDirectory

from . import crypto, services
from .authority import MfaAuthority, MfaRule, PrimaryAuthentication, PrimaryResult
from .models import Factor, Proof

PASSWORDS = {
    name: f"Fabricated-independent-{name}-knowledge-factor-2026"
    for name in ("mufti", "other", "admin")
}
PASSWORD_HASHES = {name: make_password(value) for name, value in PASSWORDS.items()}
FEATURES = {
    "FATWA_STAFF_SESSIONS_ENABLED": True,
    "FATWA_STAFF_SESSION_RUNTIME_EPOCH": "synthetic-staff-mfa-runtime-generation-0001",
    "FATWA_STAFF_MFA_ENABLED": True,
}


class Directory(PrimaryAuthentication, SessionDirectory):
    provider_id = "synthetic-mfa-directory"
    primary_method_id = "SYNTHETIC-PBKDF2-password.v1"

    def __init__(self, ref):
        super().__init__(ref)
        self.factor_kind = "KNOWLEDGE"
        self.primary_hook = None

    def projection_epoch(self):
        return repr((super().projection_epoch(), self.primary_method_id, self.factor_kind))

    def authenticate(self, credential):
        for subject, hashed in PASSWORD_HASHES.items():
            if type(credential) is str and check_password(credential, hashed):
                return self.resolve(subject)
        return None

    def authenticate_primary(self, credential, *, challenge):
        try:
            actor = self.authenticate(credential)
            if self.primary_hook:
                self.primary_hook()
            return PrimaryResult(
                actor, challenge, timezone.now(), self.primary_method_id, self.factor_kind
            )
        finally:
            from django.db import connections

            connections.close_all()


class SessionAuthority(BaseSessionAuthority):
    """Exact MFA fixture realm; never enroll another helper's synthetic account."""

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        target = values["resource"]
        return (
            values["provider_id"] == Directory.provider_id
            and values["subject_id"] in PASSWORDS
            and values["auth_epoch"] == "epoch-1"
            and values["role"]
            == ("ORGANIZER_ADMIN" if values["subject_id"] == "admin" else "MUFTI")
            and values["action"] in {"ISSUE", "USE", "LIST", "READ", "REVOKE", "LOGOUT", "AUDIT"}
            and values["action"] not in self.denied
            and target["provider_id"] == Directory.provider_id
            and target["surface"] in {"CASEWORK", "OPERATIONS"}
            and (
                target["subject_id"] == values["subject_id"]
                or (values["subject_id"] == "admin" and target.get("id") in self.admin_targets)
            )
            and timezone.now() < self.until
        )


class Authority(MfaAuthority):
    def __init__(self):
        self.denied = set()
        self.rule = MfaRule("SHA1", 6, 30, 1, 3, 180, 300, 3)
        self.until = timezone.now() + timedelta(minutes=30)
        self.hook = None

    def projection_epoch(self):
        return repr((sorted(self.denied), self.rule, self.until.isoformat()))

    def parameters(self, **values):
        return self.rule

    def grant_deadline(self, **values):
        return self.until

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        target = values["resource"]
        return (
            values["provider_id"] == Directory.provider_id
            and values["subject_id"] in PASSWORDS
            and values["role"]
            == ("ORGANIZER_ADMIN" if values["subject_id"] == "admin" else "MUFTI")
            and values["auth_epoch"] == "epoch-1"
            and target["provider_id"] == Directory.provider_id
            and target["subject_id"] == values["subject_id"]
            and values["action"] in services.ACTIONS
            and values["action"] not in self.denied
            and timezone.now() < self.until
        )


class MfaFixture:
    def setUp(self):
        super().setUp()
        self.receipt = new_case()
        self.directory = Directory(self.receipt["public_ref"])
        self.authority = Authority()
        self.session_authority = SessionAuthority()
        self.key = Fernet.generate_key()
        self.enterContext(
            override_settings(
                FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
                FATWA_STAFF_SESSION_AUTHORITY=self.session_authority,
                FATWA_STAFF_MFA_AUTHORITY=self.authority,
                FATWA_STAFF_MFA_KEY=self.key,
            )
        )

    def start(self, subject="mufti", *, binding="b" * 64, surface="CASEWORK", purpose="LOGIN"):
        return services.start(
            provider=self.directory,
            credential=PASSWORDS[subject],
            surface=surface,
            browser_binding=binding,
            purpose=purpose,
            expected_actor=self.directory.resolve(subject) if purpose == "REVOKE" else None,
        )

    def common(self, *, binding="b" * 64, surface="CASEWORK"):
        return dict(provider=self.directory, browser_binding=binding, surface=surface)

    def otp(self, factor, *, offset=0):
        secret = crypto.unseal(
            cipher=factor.secret_ciphertext, key=self.key, binding=factor.secret_binding
        )
        return crypto.generate(
            secret=secret,
            algorithm=factor.algorithm,
            digits=factor.digits,
            period=factor.period,
            at=int(timezone.now().timestamp()) + offset * factor.period,
        )

    def used_otp(self, factor):
        counter = Proof.objects.filter(factor=factor).order_by("created_at").first().counter
        secret = crypto.unseal(
            cipher=factor.secret_ciphertext, key=self.key, binding=factor.secret_binding
        )
        return crypto.generate(
            secret=secret,
            algorithm=factor.algorithm,
            digits=factor.digits,
            period=factor.period,
            at=counter * factor.period,
        )

    def finish(
        self, challenge, factor, *, offset=0, binding="b" * 64, surface="CASEWORK", code=None
    ):
        with services.complete(
            challenge.id,
            code=code if code is not None else self.otp(factor, offset=offset),
            **self.common(binding=binding, surface=surface),
        ) as (grant, codes):
            session_id = sessions.issue(
                provider=self.directory,
                actor=grant.guard.actor,
                surface=surface,
                browser_binding="c" * 64,
                deadline=timezone.now() + timedelta(minutes=5),
                mfa_grant=grant,
            )
            proof_id = str(grant.proof.id)
        return session_id, proof_id, codes

    def enrolled(self, subject="mufti", *, surface="CASEWORK"):
        challenge = self.start(subject, surface=surface)
        factor, manual = services.enroll(challenge.id, **self.common(surface=surface))
        self.assertEqual(
            base64.b32encode(
                crypto.unseal(
                    cipher=factor.secret_ciphertext, key=self.key, binding=factor.secret_binding
                )
            )
            .decode()
            .rstrip("="),
            manual,
        )
        session_id, proof_id, codes = self.finish(challenge, factor, offset=-1, surface=surface)
        return factor, session_id, proof_id, codes

    def bound(self, session_id, proof_id, subject="mufti", *, surface="CASEWORK"):
        return sessions.bind(
            provider=self.directory,
            actor=self.directory.resolve(subject),
            session_id=session_id,
            surface=surface,
            browser_binding="c" * 64,
            deadline=sessions.get(session_id).expires_at,
            lease=session_context.Lease(),
            mfa_proof=proof_id,
        )

    def current_factor(self):
        proof = Proof.objects.filter(purpose="ENROLL").order_by("-created_at").first()
        return Factor.objects.get(pk=proof.factor_id)
