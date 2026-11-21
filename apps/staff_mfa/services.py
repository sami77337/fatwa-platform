"""Finite human MFA workflow, exact current authority and immutable use history."""

import base64
import re
import secrets
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from hmac import compare_digest

from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.delivery_queue.services import synthetic_queue_atomic
from apps.mufti_review.identity import IdentityUnavailable, _ref
from apps.staff_sessions import services as sessions

from . import crypto, execution, integration
from .authority import MfaAuthority, MfaRule, PrimaryAuthentication, PrimaryResult
from .models import (
    Account,
    Attempt,
    Challenge,
    Factor,
    FactorRevocation,
    Proof,
    RecoveryCode,
    RecoveryUse,
    SessionAssurance,
)

checked, digest, encode = sessions.checked, sessions.digest, sessions.encode
_ISSUING = ContextVar("fatwa_mfa_exact_issuance", default=None)
ACTIONS = frozenset({"START", "ENROLL", "VERIFY", "RECOVER", "REVOKE", "USE", "AUDIT"})


def reject():
    raise IdentityUnavailable("staff_mfa_not_authorized")


def create(model, **values):
    normalized = {}
    for name, value in values.items():
        field = model._meta.get_field(name)
        normalized[field.attname] = (
            value.pk if field.is_relation and value is not None and hasattr(value, "pk") else value
        )
    return sessions.create(model, **normalized)


def enabled():
    return getattr(settings, "FATWA_STAFF_MFA_ENABLED", False) is True


def configured(provider):
    sessions.configured(provider)
    authority = getattr(settings, "FATWA_STAFF_MFA_AUTHORITY", None)
    key = getattr(settings, "FATWA_STAFF_MFA_KEY", None)
    if (
        not enabled()
        or not apps.is_installed("apps.staff_mfa")
        or not isinstance(authority, MfaAuthority)
        or not isinstance(provider, PrimaryAuthentication)
        or not _ref(getattr(provider, "primary_method_id", None))
        or type(key) is not bytes
        or len(key) != 44
    ):
        reject()
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise IdentityUnavailable("staff_mfa_key_unavailable") from exc
    return authority, key


def parameters(value):
    if (
        type(value) is not MfaRule
        or value.algorithm not in crypto.ALGORITHMS
        or type(value.digits) is not int
        or value.digits not in {6, 8}
        or type(value.period) is not int
        or value.period not in {30, 60}
        or type(value.window) is not int
        or value.window not in {0, 1}
        or type(value.max_failures) is not int
        or not 1 <= value.max_failures <= 10
        or type(value.challenge_seconds) is not int
        or not 1 <= value.challenge_seconds <= 300
        or type(value.session_seconds) is not int
        or not 1 <= value.session_seconds <= 900
        or type(value.recovery_codes) is not int
        or not 0 <= value.recovery_codes <= 10
    ):
        reject()
    return value


@dataclass
class Guard:
    provider: object
    actor: object
    authority: object
    key: bytes = field(repr=False)
    authority_epoch: str
    directory_epoch: str
    runtime: str
    rule: MfaRule
    deadline: datetime
    method: str

    def pure(self):
        authority, key = configured(self.provider)
        if (
            authority is not self.authority
            or not compare_digest(key, self.key)
            or sessions.epoch(self.authority) != self.authority_epoch
            or sessions.epoch(self.provider) != self.directory_epoch
            or sessions.runtime_digest() != self.runtime
            or self.provider.primary_method_id != self.method
            or self.deadline <= timezone.now()
        ):
            reject()

    def recheck(self):
        self.pure()
        current = sessions.identity(self.provider.resolve(self.actor.subject_id))
        if (
            sessions.claims(current) != sessions.claims(self.actor)
            or current.valid_until < self.deadline
        ):
            reject()
        self.pure()

    def permit(self, action, resource):
        if action not in ACTIONS:
            reject()
        try:
            allowed = self.authority.permits(
                **sessions.actor_values(self.provider, self.actor), action=action, resource=resource
            )
        except Exception as exc:
            raise IdentityUnavailable("staff_mfa_policy_unavailable") from exc
        if allowed is not True:
            reject()
        try:
            deadline = self.authority.grant_deadline(
                **sessions.actor_values(self.provider, self.actor), action=action, resource=resource
            )
        except Exception as exc:
            raise IdentityUnavailable("staff_mfa_grant_deadline_required") from exc
        if (
            not isinstance(deadline, datetime)
            or not timezone.is_aware(deadline)
            or deadline.utcoffset() != timedelta(0)
            or not timezone.now() < deadline <= timezone.now() + timedelta(hours=1)
        ):
            reject()
        self.deadline = min(self.deadline, deadline)
        self.pure()


def scope(provider, actor):
    authority, key = configured(provider)
    actor = sessions.identity(actor)
    authority_epoch, directory_epoch = sessions.epoch(authority), sessions.epoch(provider)
    try:
        rule = parameters(authority.parameters(**sessions.actor_values(provider, actor)))
    except Exception as exc:
        raise IdentityUnavailable("staff_mfa_policy_unavailable") from exc
    guard = Guard(
        provider,
        actor,
        authority,
        key,
        authority_epoch,
        directory_epoch,
        sessions.runtime_digest(),
        rule,
        actor.valid_until,
        provider.primary_method_id,
    )
    guard.pure()
    return guard


def account_resource(account, *, factor=None, challenge=None, session=None):
    return {
        "account_id": str(account.id),
        "provider_id": account.provider_id,
        "subject_id": account.subject_id,
        "factor_id": str(factor.id) if factor else "",
        "factor_digest": factor.digest if factor else "",
        "challenge_id": str(challenge.id) if challenge else "",
        "purpose": challenge.purpose if challenge else "",
        "session_id": str(session.id) if session else "",
    }


def account_for(provider, actor):
    row = Account.objects.filter(
        provider_id=provider.provider_id, subject_id=actor.subject_id
    ).first()
    if row is None:
        try:
            with transaction.atomic():
                row = create(Account, provider_id=provider.provider_id, subject_id=actor.subject_id)
        except IntegrityError:
            row = Account.objects.get(provider_id=provider.provider_id, subject_id=actor.subject_id)
    return checked(Account.objects.select_for_update().get(pk=row.pk))


def activated(account):
    rows = list(
        Factor.objects.filter(account=account, proofs__purpose="ENROLL").order_by(
            "-proofs__created_at", "-pk"
        )[:65]
    )
    if len(rows) > 64:
        reject()
    for row in rows:
        checked(row)
    return rows


def active(account):
    rows = [
        row
        for row in activated(account)
        if not FactorRevocation.objects.filter(factor=row).exists()
    ]
    if len(rows) > 1:
        reject()
    return rows[0] if rows else None


def factor_current(row, guard, *, allow_revoked=False):
    checked(row)
    if (
        row.runtime_digest != guard.runtime
        or row.key_digest != digest(guard.key.decode())
        or row.algorithm != guard.rule.algorithm
        or row.digits != guard.rule.digits
        or row.period != guard.rule.period
        or (not allow_revoked and FactorRevocation.objects.filter(factor=row).exists())
    ):
        reject()


def _challenge_pin(row):
    """Pure sealed database state used by an already-authorized native response."""
    queries = (
        Account.objects.filter(pk=row.account_id),
        Challenge.objects.filter(pk=row.pk),
        Factor.objects.filter(account_id=row.account_id, proofs__purpose="ENROLL"),
        FactorRevocation.objects.filter(factor__account_id=row.account_id),
        Factor.objects.filter(challenge=row),
        Proof.objects.filter(challenge=row),
        RecoveryUse.objects.filter(challenge=row),
        SessionAssurance.objects.filter(proof__challenge=row),
    )
    result = []
    for query in queries:
        rows = list(query.order_by("pk")[:65])
        if len(rows) > 64:
            reject()
        result.append(tuple((str(checked(value).pk), value.digest) for value in rows))
    return tuple(result)


def _retain_challenge(guard, row, *, issued=()):
    if not integration.retaining():
        return
    baseline = _challenge_pin(row)
    issued = tuple(issued)

    def pure_final():
        guard.pure()
        if _challenge_pin(row) != baseline:
            reject()
        for session, authority, epoch in issued:
            if (
                sessions.configured(guard.provider) is not authority
                or sessions.epoch(authority) != epoch
                or session.expires_at <= timezone.now()
                or sessions.SessionRevocation.objects.filter(session=session).exists()
            ):
                reject()
        guard.pure()

    integration.retain(pure_final)


def _retain_factor(guard, account, factor):
    if not integration.retaining():
        return

    def pure_final():
        guard.pure()
        current = active(account)
        if current is None or current.pk != factor.pk or current.digest != factor.digest:
            reject()
        factor_current(current, guard)
        guard.pure()

    integration.retain(pure_final)


def start(*, provider, credential, surface, browser_binding, purpose="LOGIN", expected_actor=None):
    if connection.in_atomic_block:
        raise IdentityUnavailable("staff_mfa_primary_outer_boundary_required")
    authority, key = configured(provider)
    before = sessions.epoch(authority), sessions.epoch(provider)
    if (
        surface not in sessions.SURFACES
        or purpose not in {"LOGIN", "REVOKE"}
        or (purpose == "REVOKE" and expected_actor is None)
        or (purpose == "LOGIN" and expected_actor is not None)
        or type(credential) is not str
        or not 1 <= len(credential) <= 1024
        or "\x00" in credential
        or type(browser_binding) is not str
        or re.fullmatch(r"[a-f0-9]{64}", browser_binding) is None
    ):
        reject()
    nonce, started = secrets.token_hex(32), timezone.now()
    verified = execution.primary(provider, credential, nonce)
    finished = timezone.now()
    if (
        type(verified) is not PrimaryResult
        or verified.factor_kind != "KNOWLEDGE"
        or verified.challenge != nonce
        or verified.method_id != provider.primary_method_id
        or not isinstance(verified.verified_at, datetime)
        or not timezone.is_aware(verified.verified_at)
        or verified.verified_at.utcoffset() != timedelta(0)
        or not started <= verified.verified_at <= finished
        or finished - started > timedelta(seconds=20)
        or before != (sessions.epoch(authority), sessions.epoch(provider))
        or configured(provider)[0] is not authority
        or configured(provider)[1] != key
    ):
        reject()
    guard = scope(provider, verified.identity)
    if expected_actor is not None and sessions.claims(
        sessions.identity(expected_actor)
    ) != sessions.claims(guard.actor):
        reject()
    if surface == "CASEWORK" and guard.actor.role != "MUFTI":
        reject()
    guard.recheck()
    with synthetic_queue_atomic():
        account = account_for(provider, guard.actor)
        factor = active(account)
        if factor is None:
            previous = activated(account)
            factor = previous[0] if previous else None
        if purpose == "REVOKE" and (
            factor is None or FactorRevocation.objects.filter(factor=factor).exists()
        ):
            reject()
        if factor:
            factor_current(factor, guard, allow_revoked=purpose == "LOGIN")
        guard.permit("START", account_resource(account, factor=factor))
        row = create(
            Challenge,
            account=account,
            factor=factor,
            factor_digest=factor.digest if factor else "",
            role=guard.actor.role,
            auth_epoch=guard.actor.auth_epoch,
            surface=surface,
            purpose=purpose,
            claims_digest=digest(sessions.claims(guard.actor)),
            browser_digest=digest(browser_binding),
            authority_digest=digest(guard.authority_epoch),
            directory_digest=digest(guard.directory_epoch),
            runtime_digest=guard.runtime,
            key_digest=digest(guard.key.decode()),
            rule_payload=encode(asdict(guard.rule)),
            nonce_digest=digest(nonce),
            primary_method=verified.method_id,
            primary_verified_at=verified.verified_at,
            actor_deadline=guard.actor.valid_until,
            expires_at=min(
                guard.deadline, finished + timedelta(seconds=guard.rule.challenge_seconds)
            ),
        )
        guard.recheck()
        if factor:
            factor_current(factor, guard, allow_revoked=purpose == "LOGIN")
        guard.pure()
        _retain_challenge(guard, row)
    return row


def challenge_guard(challenge_id, *, provider, surface, browser_binding, lock=False):
    try:
        row = checked(
            Challenge.objects.select_related("account").get(pk=sessions.uid(challenge_id))
        )
    except Challenge.DoesNotExist as exc:
        raise IdentityUnavailable("staff_mfa_challenge_required") from exc
    account = checked(row.account)
    if lock:
        checked(Account.objects.select_for_update().get(pk=account.pk))
    guard = scope(provider, sessions.identity(provider.resolve(account.subject_id)))
    if (
        account.provider_id != provider.provider_id
        or row.surface != surface
        or row.browser_digest != digest(browser_binding)
        or row.auth_epoch != guard.actor.auth_epoch
        or row.role != guard.actor.role
        or row.claims_digest != digest(sessions.claims(guard.actor))
        or row.authority_digest != digest(guard.authority_epoch)
        or row.directory_digest != digest(guard.directory_epoch)
        or row.runtime_digest != guard.runtime
        or row.key_digest != digest(guard.key.decode())
        or row.primary_method != provider.primary_method_id
        or row.rule_payload != encode(asdict(guard.rule))
        or row.expires_at <= timezone.now()
        or Proof.objects.filter(challenge=row).exists()
    ):
        reject()
    guard.deadline = min(guard.deadline, row.expires_at, row.actor_deadline)
    guard.recheck()
    if row.factor_id:
        factor = checked(Factor.objects.get(pk=row.factor_id))
        if factor.account_id != account.id or factor.digest != row.factor_digest:
            reject()
        factor_current(factor, guard, allow_revoked=True)
    return guard, row


def describe(challenge_id, **common):
    with synthetic_queue_atomic():
        guard, row = challenge_guard(challenge_id, **common, lock=True)
        factor = active(row.account)
        recovered = RecoveryUse.objects.filter(challenge=row).exists()
        guard.permit("START", account_resource(row.account, factor=factor, challenge=row))
        value = {
            "id": str(row.id),
            "surface": row.surface,
            "purpose": row.purpose,
            "has_factor": factor is not None,
            "can_enroll": row.purpose == "LOGIN"
            and factor is None
            and (not activated(row.account) or recovered),
            "pending": Factor.objects.filter(challenge=row).exists(),
            "can_recover": row.purpose == "LOGIN" and row.factor_id is not None and not recovered,
        }
        guard.recheck()
        guard.pure()
        _retain_challenge(guard, row)
        return value


def enroll(challenge_id, **common):
    with synthetic_queue_atomic():
        guard, row = challenge_guard(challenge_id, **common, lock=True)
        recovery = RecoveryUse.objects.filter(challenge=row).first()
        if (
            row.purpose != "LOGIN"
            or active(row.account) is not None
            or (activated(row.account) and recovery is None)
            or Factor.objects.filter(challenge=row).exists()
        ):
            reject()
        if recovery:
            checked(recovery)
            if activated(row.account)[0].id != row.factor_id:
                reject()
        guard.permit("ENROLL", account_resource(row.account, challenge=row))
        identifier = uuid.uuid4()
        binding = digest(
            [
                str(row.account_id),
                str(identifier),
                guard.rule.algorithm,
                guard.rule.digits,
                guard.rule.period,
            ]
        )
        secret = secrets.token_bytes({"SHA1": 20, "SHA256": 32, "SHA512": 64}[guard.rule.algorithm])
        factor = create(
            Factor,
            id=identifier,
            account=row.account,
            challenge=row,
            secret_ciphertext=crypto.seal(secret=secret, key=guard.key, binding=binding),
            secret_binding=binding,
            key_digest=digest(guard.key.decode()),
            runtime_digest=guard.runtime,
            algorithm=guard.rule.algorithm,
            digits=guard.rule.digits,
            period=guard.rule.period,
        )
        guard.recheck()
        if active(row.account) is not None:
            reject()
        factor_current(factor, guard)
        guard.pure()
        _retain_challenge(guard, row)
    return factor, base64.b32encode(secret).decode("ascii").rstrip("=")


def _attempt_capacity(account, kind, rule):
    last = Attempt.objects.filter(account=account, accepted=True).order_by("-created_at").first()
    failures = Attempt.objects.filter(account=account, kind=kind, accepted=False)
    if last:
        checked(last)
        failures = failures.filter(created_at__gt=last.created_at)
    if failures.count() >= rule.max_failures:
        reject()


def _selected_factor(row, guard):
    factor = Factor.objects.filter(challenge=row).first()
    if factor is not None:
        if active(row.account) is not None:
            reject()
        if activated(row.account) and not RecoveryUse.objects.filter(challenge=row).exists():
            reject()
        if activated(row.account) and activated(row.account)[0].id != row.factor_id:
            reject()
        purpose = "ENROLL"
    else:
        factor = active(row.account)
        if factor is None or row.factor_id != factor.id or row.factor_digest != factor.digest:
            reject()
        purpose = row.purpose
    factor_current(factor, guard)
    return factor, purpose


@dataclass(frozen=True, slots=True)
class Issuance:
    guard: Guard
    challenge: Challenge
    factor: Factor
    proof: Proof
    issued: list = field(default_factory=list)


def _codes(row, proof, count):
    result = []
    for slot in range(count):
        token = "r-" + secrets.token_hex(32)
        create(
            RecoveryCode,
            account=row.account,
            factor=proof.factor,
            activation=proof,
            slot=slot,
            code_digest=digest([str(row.account_id), str(proof.factor_id), token]),
        )
        result.append(token)
    return result


@contextmanager
def complete(challenge_id, *, code, **common):
    refused = False
    with synthetic_queue_atomic():
        guard, row = challenge_guard(challenge_id, **common, lock=True)
        factor, purpose = _selected_factor(row, guard)
        guard.permit(
            "REVOKE" if purpose == "REVOKE" else "VERIFY",
            account_resource(row.account, factor=factor, challenge=row),
        )
        _attempt_capacity(row.account, "OTP", guard.rule)
        secret = crypto.unseal(
            cipher=factor.secret_ciphertext, key=guard.key, binding=factor.secret_binding
        )
        try:
            counter = crypto.match(
                secret=secret,
                algorithm=factor.algorithm,
                digits=factor.digits,
                period=factor.period,
                code=code,
                at=int(timezone.now().timestamp()),
                window=guard.rule.window,
            )
        except ValueError:
            counter = None
        del secret
        if counter is None or Proof.objects.filter(factor=factor, counter=counter).exists():
            create(Attempt, account=row.account, challenge=row, kind="OTP", accepted=False)
            guard.recheck()
            factor_current(factor, guard)
            guard.pure()
            refused = True
        else:
            now = timezone.now()
            proof = create(
                Proof,
                account=row.account,
                factor=factor,
                challenge=row,
                purpose=purpose,
                counter=counter,
                verified_at=now,
                expires_at=min(
                    row.actor_deadline, now + timedelta(seconds=guard.rule.session_seconds)
                ),
            )
            guard.deadline = min(guard.deadline, proof.expires_at)
            create(Attempt, account=row.account, challenge=row, kind="OTP", accepted=True)
            codes = _codes(row, proof, guard.rule.recovery_codes) if purpose == "ENROLL" else []
            grant = Issuance(guard, row, factor, proof)
            token = _ISSUING.set(grant)
            try:
                yield grant, codes
                guard.recheck()
                if purpose == "REVOKE":
                    if not FactorRevocation.objects.filter(factor=factor, proof=proof).exists():
                        reject()
                elif not SessionAssurance.objects.filter(proof=proof).exists():
                    reject()
                factor_current(factor, guard, allow_revoked=purpose == "REVOKE")
                for session, authority, epoch in grant.issued:
                    if (
                        sessions.configured(guard.provider) is not authority
                        or sessions.epoch(authority) != epoch
                        or session.expires_at <= timezone.now()
                        or sessions.SessionRevocation.objects.filter(session=session).exists()
                    ):
                        reject()
                guard.pure()
                _retain_challenge(guard, row, issued=grant.issued)
            finally:
                _ISSUING.reset(token)
    if refused:
        reject()


def issuance(grant, *, provider, actor, surface):
    if type(grant) is not Issuance or _ISSUING.get() is not grant or not connection.in_atomic_block:
        reject()
    if (
        grant.guard.provider is not provider
        or sessions.claims(actor) != sessions.claims(grant.guard.actor)
        or grant.challenge.surface != surface
        or grant.proof.purpose == "REVOKE"
        or grant.proof.expires_at <= timezone.now()
        or SessionAssurance.objects.filter(proof=grant.proof).exists()
    ):
        reject()
    grant.guard.recheck()
    factor_current(grant.factor, grant.guard)
    return grant


def attach(session, grant, *, provider, actor, surface):
    issuance(grant, provider=provider, actor=actor, surface=surface)
    if (
        session.provider_id,
        session.subject_id,
        session.role,
        session.auth_epoch,
        session.surface,
    ) != (provider.provider_id, actor.subject_id, actor.role, actor.auth_epoch, surface):
        reject()
    result = create(
        SessionAssurance,
        session=session,
        proof=grant.proof,
        expires_at=min(session.expires_at, grant.proof.expires_at),
    )
    session_authority = sessions.configured(provider)
    grant.issued.append((session, session_authority, sessions.epoch(session_authority)))
    grant.guard.pure()
    return result


def revoke(grant):
    if (
        type(grant) is not Issuance
        or _ISSUING.get() is not grant
        or grant.proof.purpose != "REVOKE"
    ):
        reject()
    grant.guard.recheck()
    factor_current(grant.factor, grant.guard)
    result = create(
        FactorRevocation,
        factor=grant.factor,
        challenge=grant.challenge,
        proof=grant.proof,
        recovery_code=None,
        reason="USER_REVOKE",
    )
    grant.guard.pure()
    return result


def recover(challenge_id, *, recovery_code, **common):
    refused = False
    with synthetic_queue_atomic():
        guard, row = challenge_guard(challenge_id, **common, lock=True)
        if (
            row.purpose != "LOGIN"
            or row.factor_id is None
            or RecoveryUse.objects.filter(challenge=row).exists()
        ):
            reject()
        factor = checked(Factor.objects.get(pk=row.factor_id))
        factor_current(factor, guard, allow_revoked=True)
        current = active(row.account)
        if current is not None and current.pk != factor.pk:
            reject()
        history = activated(row.account)
        if not history or history[0].pk != factor.pk:
            reject()
        guard.permit("RECOVER", account_resource(row.account, factor=factor, challenge=row))
        _attempt_capacity(row.account, "RECOVERY", guard.rule)
        code = None
        if type(recovery_code) is str and re.fullmatch(r"r-[a-f0-9]{64}", recovery_code):
            candidate = digest([str(row.account_id), str(factor.id), recovery_code])
            code = RecoveryCode.objects.filter(
                account=row.account, factor=factor, code_digest=candidate
            ).first()
        if code is None or RecoveryUse.objects.filter(code=code).exists():
            create(Attempt, account=row.account, challenge=row, kind="RECOVERY", accepted=False)
            refused = True
        else:
            checked(code)
            revocation = FactorRevocation.objects.filter(factor=factor).first()
            if revocation is None:
                revocation = create(
                    FactorRevocation,
                    factor=factor,
                    challenge=row,
                    proof=None,
                    recovery_code=code,
                    reason="RECOVERY",
                )
            else:
                checked(revocation)
            create(RecoveryUse, code=code, challenge=row, revocation=revocation)
            create(Attempt, account=row.account, challenge=row, kind="RECOVERY", accepted=True)
        guard.recheck()
        factor_current(factor, guard, allow_revoked=True)
        guard.pure()
        if not refused:
            _retain_challenge(guard, row)
    if refused:
        reject()


@dataclass(frozen=True, slots=True)
class Use:
    guard: Guard
    session_id: str
    assurance_id: str
    assurance_digest: str
    factor_id: str
    factor_digest: str
    deadline: datetime


def capture(*, provider, actor, session_id, proof_id):
    guard = scope(provider, actor)
    try:
        row = checked(
            SessionAssurance.objects.select_related(
                "proof__factor__account", "proof__challenge"
            ).get(session_id=sessions.uid(session_id), proof_id=sessions.uid(proof_id))
        )
    except SessionAssurance.DoesNotExist as exc:
        raise IdentityUnavailable("staff_mfa_session_proof_required") from exc
    proof, factor, challenge = (
        checked(row.proof),
        checked(row.proof.factor),
        checked(row.proof.challenge),
    )
    account = checked(factor.account)
    if (
        account.provider_id != provider.provider_id
        or account.subject_id != actor.subject_id
        or challenge.role != actor.role
        or challenge.auth_epoch != actor.auth_epoch
        or challenge.claims_digest != digest(sessions.claims(actor))
        or challenge.runtime_digest != guard.runtime
        or proof.purpose not in {"LOGIN", "ENROLL"}
    ):
        reject()
    guard.deadline = min(guard.deadline, row.expires_at)
    use = Use(
        guard,
        str(session_id),
        str(row.pk),
        row.digest,
        str(factor.id),
        factor.digest,
        guard.deadline,
    )
    check(use)
    return use


def check(use, *, authorize=True, lock=False):
    if type(use) is not Use:
        reject()
    guard = use.guard
    guard.pure()
    row = checked(
        SessionAssurance.objects.select_related("proof__factor__account").get(pk=use.assurance_id)
    )
    factor, account = checked(row.proof.factor), checked(row.proof.factor.account)
    if lock:
        checked(Account.objects.select_for_update().get(pk=account.pk))
    if (
        row.digest != use.assurance_digest
        or str(row.session_id) != use.session_id
        or str(factor.id) != use.factor_id
        or factor.digest != use.factor_digest
        or row.expires_at < use.deadline
        or use.deadline <= timezone.now()
    ):
        reject()
    factor_current(factor, guard)
    if authorize:
        guard.permit("USE", account_resource(account, factor=factor, session=row.session))
        check(use, authorize=False, lock=lock)
    guard.pure()
    return row


def manage(*, provider, actor):
    with synthetic_queue_atomic():
        guard = scope(provider, actor)
        try:
            account = checked(
                Account.objects.select_for_update().get(
                    provider_id=provider.provider_id, subject_id=actor.subject_id
                )
            )
        except Account.DoesNotExist as exc:
            raise IdentityUnavailable("staff_mfa_account_required") from exc
        factor = active(account)
        if factor is None:
            reject()
        factor_current(factor, guard)
        guard.permit("AUDIT", account_resource(account, factor=factor))
        result = {
            "factor_id": str(factor.id),
            "algorithm": factor.algorithm,
            "digits": factor.digits,
            "period": factor.period,
            "role": actor.role,
        }
        guard.recheck()
        factor_current(factor, guard)
        guard.pure()
        _retain_factor(guard, account, factor)
        return result


def history_queries(account_id):
    return (
        Account.objects.filter(pk=account_id),
        Challenge.objects.filter(account_id=account_id),
        Factor.objects.filter(account_id=account_id),
        Proof.objects.filter(account_id=account_id),
        Attempt.objects.filter(account_id=account_id),
        RecoveryCode.objects.filter(account_id=account_id),
        FactorRevocation.objects.filter(factor__account_id=account_id),
        RecoveryUse.objects.filter(code__account_id=account_id),
        SessionAssurance.objects.filter(proof__account_id=account_id),
    )


def audit(*, provider, actor, account_id):
    """New exact trusted audit only; no seed, cookie, recovery code or login proof."""
    with synthetic_queue_atomic():
        guard = scope(provider, actor)
        try:
            account = checked(Account.objects.select_for_update().get(pk=sessions.uid(account_id)))
        except Account.DoesNotExist as exc:
            raise IdentityUnavailable("staff_mfa_account_required") from exc
        if (account.provider_id, account.subject_id) != (provider.provider_id, actor.subject_id):
            reject()
        guard.permit("AUDIT", account_resource(account))
        pins = []
        counts = {}
        for query in history_queries(account.id):
            rows = list(query.order_by("pk")[:4097])
            if len(rows) > 4096:
                reject()
            for row in rows:
                checked(row)
            pins.append(tuple((str(row.pk), row.digest) for row in rows))
            counts[query.model._meta.model_name] = len(rows)
        guard.recheck()
        current = [
            tuple((str(pk), seal) for pk, seal in query.order_by("pk").values_list("pk", "digest"))
            for query in history_queries(account.id)
        ]
        if pins != current:
            reject()
        guard.pure()
        return counts
