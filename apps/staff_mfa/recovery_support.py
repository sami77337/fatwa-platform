"""Restored MFA history is evidence, never a resumed authentication capability."""

import unittest
from contextlib import contextmanager
from dataclasses import replace

from cryptography.fernet import Fernet
from django.conf import settings
from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, CaseDecision, CaseEvidence, CaseSource
from apps.mufti_review.identity import IdentityUnavailable
from apps.staff_sessions import integration as session_context
from apps.staff_sessions import services as sessions

from . import history, services
from .models import Account
from .test_support import FEATURES, PASSWORDS, Authority, Directory, MfaFixture, SessionAuthority

NAMES = (
    "account",
    "challenge",
    "factor",
    "proof",
    "attempt",
    "recoverycode",
    "factorrevocation",
    "recoveryuse",
    "sessionassurance",
)
TABLES = tuple("staff_mfa_" + name for name in NAMES)
FUNCTIONS = ("staff_mfa_history_guard()",)
TRIGGERS = tuple("staff_mfa_" + name + "_guard" for name in NAMES)
DENIALS = (
    "mfa_disabled",
    "missing_key",
    "missing_authority",
    "missing_directory",
    "session_registry_disabled",
    "missing_runtime_epoch",
    "revoked_audit_grant",
    "cross_actor_audit",
    "inactive_actor",
    "restored_primary_challenge",
    "restored_session_assurance",
    "restored_factor_login",
    "restored_legacy_factor_veto",
    "restored_legacy_missing_app",
)


def rows(account_id):
    result = {}
    for query in services.history_queries(account_id):
        if not query.exists():
            raise AssertionError("restored MFA history table is empty")
        result[query.model._meta.db_table] = services.digest(list(query.order_by("pk").values()))
    return result


def sources(case_id):
    return {
        model._meta.db_table: services.digest(
            list(model.objects.filter(case_id=case_id).order_by("pk").values())
        )
        for model in (CaseSource, CaseEvidence, AnswerRevision, CaseDecision)
    }


def populate():
    class Fixture(MfaFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    configured = override_settings(**FEATURES)
    configured.enable()
    try:
        fixture.setUp()
        common = dict(
            case_id=fixture.receipt["case_id"],
            subject_id="mufti",
            provider=fixture.directory,
            synthetic_fixtures_only=True,
        )
        draft = cases.save_answer(
            **common,
            text="جواب بشري اصطناعي محفوظ أثناء فحص المصادقة.\n",
            expected_revision=1,
            expected_evidence_version=1,
        )
        cases.record_decision(
            **common,
            action="APPROVE",
            answer_id=draft["answers"][-1]["id"],
            expected_revision=draft["revision"],
            expected_evidence_version=1,
        )
        _, old_session, old_proof, codes = fixture.enrolled()
        challenge = fixture.start()
        services.recover(challenge.id, recovery_code=codes[0], **fixture.common())
        factor, _ = services.enroll(challenge.id, **fixture.common())
        new_session, new_proof, _ = fixture.finish(challenge, factor, offset=-1)
        pending = fixture.start()
        account = Account.objects.get(subject_id="mufti", provider_id=fixture.directory.provider_id)
        return {
            "case": {key: fixture.receipt[key] for key in ("case_id", "public_ref")},
            "account_id": str(account.id),
            "pending": str(pending.id),
            "sessions": [old_session, new_session],
            "proofs": [old_proof, new_proof],
            "tables": rows(account.id),
            "sources": sources(fixture.receipt["case_id"]),
        }
    finally:
        fixture.doCleanups()
        configured.disable()


@contextmanager
def fresh_trust(pins):
    directory, authority, session_authority = (
        Directory(pins["case"]["public_ref"]),
        Authority(),
        SessionAuthority(),
    )
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_STAFF_MFA_AUTHORITY": authority,
            "FATWA_STAFF_MFA_KEY": Fernet.generate_key(),
            "FATWA_STAFF_SESSION_AUTHORITY": session_authority,
            "FATWA_STAFF_SESSION_RUNTIME_EPOCH": "synthetic-staff-mfa-restored-generation-0002",
        }
    ):
        yield directory, authority


def verify_restored(pins):
    if (
        rows(pins["account_id"]) != pins["tables"]
        or sources(pins["case"]["case_id"]) != pins["sources"]
    ):
        raise AssertionError("MFA history or original case bytes changed on restore")
    denial_checks = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins) as (directory, authority):
        actor = directory.resolve("mufti")

        def read(who=actor):
            return services.audit(provider=directory, actor=who, account_id=pins["account_id"])

        def positive():
            actual = read()
            if (
                actual["factor"] != 2
                or actual["factorrevocation"] != 1
                or actual["recoveryuse"] != 1
                or actual["sessionassurance"] != 2
            ):
                raise AssertionError("restored MFA consumption or factor history changed")

        def deny(name, action):
            try:
                action()
            except IdentityUnavailable:
                denial_checks[name] += 1
            else:
                raise AssertionError("restored MFA history inferred authority: " + name)

        positive()
        for name, key, value in (
            ("mfa_disabled", "FATWA_STAFF_MFA_ENABLED", False),
            ("missing_key", "FATWA_STAFF_MFA_KEY", None),
            ("missing_authority", "FATWA_STAFF_MFA_AUTHORITY", None),
            ("missing_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("session_registry_disabled", "FATWA_STAFF_SESSIONS_ENABLED", False),
            ("missing_runtime_epoch", "FATWA_STAFF_SESSION_RUNTIME_EPOCH", None),
        ):
            with override_settings(**{key: value}):
                deny(name, read)
        authority.denied.add("AUDIT")
        deny("revoked_audit_grant", read)
        authority.denied.clear()
        deny("cross_actor_audit", lambda: read(directory.resolve("other")))
        deny("inactive_actor", lambda: read(replace(actor, active=False)))
        deny(
            "restored_primary_challenge",
            lambda: services.describe(
                pins["pending"], provider=directory, surface="CASEWORK", browser_binding="b" * 64
            ),
        )
        row = sessions.Session.objects.get(pk=pins["sessions"][1])
        deny(
            "restored_session_assurance",
            lambda: sessions.bind(
                provider=directory,
                actor=actor,
                session_id=str(row.id),
                surface=row.surface,
                browser_binding="c" * 64,
                deadline=row.expires_at,
                lease=session_context.Lease(),
                mfa_proof=pins["proofs"][1],
            ),
        )
        deny(
            "restored_factor_login",
            lambda: services.start(
                provider=directory,
                credential=PASSWORDS["mufti"],
                surface="CASEWORK",
                browser_binding="b" * 64,
            ),
        )
        with override_settings(FATWA_STAFF_MFA_ENABLED=False, FATWA_STAFF_SESSIONS_ENABLED=False):
            deny(
                "restored_legacy_factor_veto",
                lambda: history.assert_legacy(directory.provider_id, actor.subject_id),
            )
            without_app = [name for name in settings.INSTALLED_APPS if name != "apps.staff_mfa"]
            with override_settings(INSTALLED_APPS=without_app):
                deny(
                    "restored_legacy_missing_app",
                    lambda: history.assert_legacy(directory.provider_id, actor.subject_id),
                )
        positive()
    if (
        rows(pins["account_id"]) != pins["tables"]
        or sources(pins["case"]["case_id"]) != pins["sources"]
    ):
        raise AssertionError("restored MFA readers changed history or original source")
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denial_checks": denial_checks,
        "denied_reads": sum(denial_checks.values()),
        "denied_read_count": sum(denial_checks.values()),
        "positive_reads_after_denial": True,
        "original_bytes_preserved": True,
        "restored_authentication_rejected": True,
        "consumed_recovery_preserved": True,
        "fresh_identity_audit_allowed": True,
        "production_assurance": "NOT_EVALUATED",
    }
