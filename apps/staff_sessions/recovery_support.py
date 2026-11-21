"""Restore audit history without restoring authentication or consumed fresh proof."""

import json
import unittest
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256

from django.test import override_settings

from apps.casework.models import AnswerRevision, CaseDecision, CaseSource
from apps.mufti_review.identity import IdentityUnavailable

from . import integration, services
from .models import FreshProof, ProofUse, Session, SessionRevocation
from .test_support import FEATURES, Authority, Directory, SessionFixture

TABLES = tuple(model._meta.db_table for model in (Session, SessionRevocation, FreshProof, ProofUse))
FUNCTIONS = ("staff_sessions_history_guard()",)
TRIGGERS = (
    "staff_sessions_session_guard",
    "staff_sessions_revocation_guard",
    "staff_sessions_proof_guard",
    "staff_sessions_use_guard",
)
DENIALS = (
    "sessions_disabled",
    "missing_authority",
    "missing_directory",
    "missing_runtime_epoch",
    "revoked_audit_grant",
    "cross_actor_audit",
    "inactive_actor",
    "restored_session_runtime",
)


def fingerprint(rows):
    return sha256(
        json.dumps(list(rows), default=str, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def rows(ids):
    queries = (
        Session.objects.filter(pk__in=ids),
        SessionRevocation.objects.filter(session_id__in=ids),
        FreshProof.objects.filter(session_id__in=ids),
        ProofUse.objects.filter(proof__session_id__in=ids),
    )
    result = {}
    for query in queries:
        if not query.exists():
            raise AssertionError("restored staff-session audit table is empty")
        result[query.model._meta.db_table] = fingerprint(query.order_by("pk").values())
    return result


def sources(case_id):
    return {
        model._meta.db_table: fingerprint(
            model.objects.filter(case_id=case_id).order_by("pk").values()
        )
        for model in (CaseSource, AnswerRevision, CaseDecision)
    }


def populate():
    class Fixture(SessionFixture, unittest.TestCase):
        pass

    fixture = Fixture()
    enabled = override_settings(**FEATURES)
    enabled.enable()
    try:
        fixture.setUp()
        response = fixture.revoke(fixture.fresh())
        if response.status_code != 303:
            raise AssertionError("synthetic fresh-proof revocation did not complete")
        identifiers = [fixture.session_id(fixture.client), fixture.session_id(fixture.other_client)]
        return {
            "case": {key: fixture.receipt[key] for key in ("case_id", "public_ref")},
            "sessions": identifiers,
            "tables": rows(identifiers),
            "sources": sources(fixture.receipt["case_id"]),
        }
    finally:
        fixture.doCleanups()
        enabled.disable()


@contextmanager
def fresh_trust(pins):
    directory, authority = Directory(pins["case"]["public_ref"]), Authority()
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_STAFF_SESSION_AUTHORITY": authority,
            "FATWA_STAFF_SESSION_RUNTIME_EPOCH": "synthetic-session-restored-generation-0002",
        }
    ):
        yield directory, authority


def verify_restored(pins):
    if (
        rows(pins["sessions"]) != pins["tables"]
        or sources(pins["case"]["case_id"]) != pins["sources"]
    ):
        raise AssertionError("staff-session history or canonical source changed on restore")
    denial_checks = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins) as (directory, authority):
        actor = directory.identities["mufti"]

        def read(who=actor):
            return services.audit(provider=directory, actor=who, session_id=pins["sessions"][0])

        def positive():
            result = read()
            revoked = services.audit(
                provider=directory, actor=actor, session_id=pins["sessions"][1]
            )
            if result["proofs"] != 1 or result["consumed"] != 1 or revoked["revoked"] is not True:
                raise AssertionError("restored fresh proof became unused or revocation disappeared")

        def deny(name, operation):
            try:
                operation()
            except IdentityUnavailable:
                denial_checks[name] += 1
            else:
                raise AssertionError("restored session inferred authority: " + name)

        positive()
        for name, key, value in (
            ("sessions_disabled", "FATWA_STAFF_SESSIONS_ENABLED", False),
            ("missing_authority", "FATWA_STAFF_SESSION_AUTHORITY", None),
            ("missing_directory", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
            ("missing_runtime_epoch", "FATWA_STAFF_SESSION_RUNTIME_EPOCH", None),
        ):
            with override_settings(**{key: value}):
                deny(name, read)
        authority.denied.add("AUDIT")
        deny("revoked_audit_grant", read)
        authority.denied.clear()
        deny("cross_actor_audit", lambda: read(directory.identities["other"]))
        deny("inactive_actor", lambda: read(replace(actor, active=False)))
        with integration.request_context() as lease:
            row = Session.objects.get(pk=pins["sessions"][0])
            attempted = services.Binding(
                str(row.id),
                directory,
                authority,
                actor,
                row.surface,
                row.browser_digest,
                row.expires_at,
                services.epoch(authority),
                services.epoch(directory),
                services.runtime_digest(),
                lease,
            )
            deny("restored_session_runtime", lambda: services.check(attempted))
        positive()
    if (
        rows(pins["sessions"]) != pins["tables"]
        or sources(pins["case"]["case_id"]) != pins["sources"]
    ):
        raise AssertionError("restored audit reads changed source or authentication history")
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "denied_reads": sum(denial_checks.values()),
        "denied_read_count": sum(denial_checks.values()),
        "denial_checks": denial_checks,
        "positive_reads_after_denial": True,
        "original_bytes_preserved": True,
        "restored_sessions_rejected": True,
        "fresh_identity_audit_allowed": True,
        "mfa_assurance": "NOT_EVALUATED",
    }
