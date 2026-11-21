"""Revocable server sessions with exact policy, durable history and human fresh proof."""

import json
import os
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from hmac import compare_digest

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone

from apps.delivery_queue.services import QueueConflict, _postgres_only, synthetic_queue_atomic
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable, MuftiIdentity, _ref, require_provider

from .authority import FreshAuthentication, FreshResult, ReauthenticationRule, SessionAuthority
from .models import FreshProof, ProofUse, Session, SessionRevocation

SURFACES = frozenset({"CASEWORK", "OPERATIONS"})
OPERATION = "REVOKE_SESSION"


def reject():
    raise IdentityUnavailable("staff_session_not_authorized")


def enabled():
    return getattr(settings, "FATWA_STAFF_SESSIONS_ENABLED", False) is True


def encode(value):
    return json.dumps(
        value,
        default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def digest(value):
    return sha256((value if isinstance(value, str) else encode(value)).encode()).hexdigest()


def claims(actor):
    return (actor.subject_id, actor.role, actor.active, sorted(actor.case_keys), actor.auth_epoch)


def identity(actor):
    now = timezone.now()
    if (
        type(actor) is not MuftiIdentity
        or not _ref(actor.subject_id)
        or actor.role not in {"MUFTI", "ORGANIZER_ADMIN", "ORGANIZER"}
        or actor.active is not True
        or not _ref(actor.auth_epoch, 64)
        or type(actor.case_keys) is not frozenset
        or not 1 <= len(actor.case_keys) <= 64
        or any(not _ref(key) for key in actor.case_keys)
        or not isinstance(actor.valid_until, datetime)
        or not timezone.is_aware(actor.valid_until)
        or actor.valid_until.utcoffset() != timedelta(0)
        or not now < actor.valid_until <= now + timedelta(hours=1)
    ):
        reject()
    return actor


def epoch(obj):
    try:
        value = obj.projection_epoch()
    except Exception as exc:
        raise IdentityUnavailable("staff_session_snapshot_required") from exc
    if type(value) is not str or not 1 <= len(value) <= 131072:
        reject()
    return value


def configured(provider):
    try:
        _postgres_only()
    except (DatabaseError, SyntheticWriteDenied, QueueConflict) as exc:
        raise IdentityUnavailable("staff_session_store_unavailable") from exc
    authority = getattr(settings, "FATWA_STAFF_SESSION_AUTHORITY", None)
    runtime = getattr(settings, "FATWA_STAFF_SESSION_RUNTIME_EPOCH", None)
    if (
        not enabled()
        or os.environ.get("FATWA_PRODUCTION") != "0"
        or provider is not getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        or not isinstance(authority, SessionAuthority)
        or type(runtime) is not str
        or not 32 <= len(runtime) <= 128
        or not runtime.isascii()
        or not _ref(runtime)
    ):
        reject()
    require_provider(provider)
    return authority


def database_identity():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), oid FROM pg_database WHERE datname=current_database()"
        )
        name, oid = cursor.fetchone()
    return f"{name}:{oid}"


def runtime_digest():
    return digest(
        [getattr(settings, "FATWA_STAFF_SESSION_RUNTIME_EPOCH", None), database_identity()]
    )


def uid(value):
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise IdentityUnavailable("staff_session_id_required") from exc
    if str(parsed) != str(value):
        reject()
    return parsed


def resource(row):
    return {
        "id": str(row.id),
        "provider_id": row.provider_id,
        "subject_id": row.subject_id,
        "role": row.role,
        "surface": row.surface,
        "digest": row.digest,
    }


def actor_values(provider, actor):
    return {
        "provider_id": provider.provider_id,
        "subject_id": actor.subject_id,
        "role": actor.role,
        "auth_epoch": actor.auth_epoch,
    }


def permit(authority, provider, actor, action, target):
    try:
        allowed = authority.permits(**actor_values(provider, actor), action=action, resource=target)
    except Exception as exc:
        raise IdentityUnavailable("staff_session_policy_unavailable") from exc
    if allowed is not True:
        reject()


def create(model, **values):
    values = {"id": uuid.uuid4(), **values}
    body = encode(values)
    return model.objects.create(**values, canonical_payload=body, digest=digest(body))


def checked(row):
    values = {
        f.attname: getattr(row, f.attname)
        for f in row._meta.concrete_fields
        if f.attname not in {"canonical_payload", "digest", "created_at"}
    }
    if row.canonical_payload != encode(values) or not compare_digest(
        row.digest, digest(row.canonical_payload)
    ):
        reject()
    return row


def get(session_id, *, lock=False):
    rows = (
        Session.objects.select_for_update()
        if lock and connection.in_atomic_block
        else Session.objects
    )
    try:
        return checked(rows.get(pk=uid(session_id)))
    except Session.DoesNotExist as exc:
        raise IdentityUnavailable("staff_session_not_authorized") from exc


def fresh_identity(provider, expected):
    configured(provider)
    before = epoch(provider)
    try:
        actor = identity(provider.resolve(expected.subject_id))
    except Exception as exc:
        raise IdentityUnavailable("staff_session_identity_unavailable") from exc
    if claims(actor) != claims(expected) or epoch(provider) != before:
        reject()
    return actor


def issue(*, provider, actor, surface, browser_binding, deadline):
    authority = configured(provider)
    actor = identity(actor)
    before = epoch(authority), epoch(provider)
    if (
        surface not in SURFACES
        or (surface == "CASEWORK" and actor.role != "MUFTI")
        or type(browser_binding) is not str
        or len(browser_binding) != 64
    ):
        reject()
    expiry = min(actor.valid_until, deadline)
    if not timezone.now() < expiry <= timezone.now() + timedelta(hours=1):
        reject()
    permit(
        authority,
        provider,
        actor,
        "ISSUE",
        {
            "id": "",
            "provider_id": provider.provider_id,
            "subject_id": actor.subject_id,
            "role": actor.role,
            "surface": surface,
            "digest": "",
        },
    )
    fresh_identity(provider, actor)
    with synthetic_queue_atomic():
        if configured(provider) is not authority or before != (epoch(authority), epoch(provider)):
            reject()
        row = create(
            Session,
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            role=actor.role,
            auth_epoch=actor.auth_epoch,
            surface=surface,
            browser_digest=digest(browser_binding),
            claims_digest=digest(claims(actor)),
            runtime_digest=runtime_digest(),
            authority_digest=digest(before[0]),
            expires_at=expiry,
        )
        if before != (epoch(authority), epoch(provider)) or expiry <= timezone.now():
            reject()
    return str(row.id)


@dataclass(frozen=True, slots=True)
class Binding:
    id: str
    provider: object
    authority: object
    actor: MuftiIdentity
    surface: str
    browser_digest: str
    deadline: datetime
    authority_epoch: str
    directory_epoch: str
    runtime: str
    lease: object


def bind(*, provider, actor, session_id, surface, browser_binding, deadline, lease):
    authority = configured(provider)
    actor = identity(actor)
    binding = Binding(
        str(uid(session_id)),
        provider,
        authority,
        actor,
        surface,
        digest(browser_binding),
        min(actor.valid_until, deadline),
        epoch(authority),
        epoch(provider),
        runtime_digest(),
        lease,
    )
    check(binding, actor=actor)
    return binding


def check(binding, *, actor=None, lock=False, authorize=True):
    if type(binding) is not Binding or not binding.lease.active:
        reject()
    if (
        configured(binding.provider) is not binding.authority
        or binding.runtime != runtime_digest()
        or binding.deadline <= timezone.now()
        or binding.authority_epoch != epoch(binding.authority)
        or binding.directory_epoch != epoch(binding.provider)
    ):
        reject()
    row = get(binding.id, lock=lock)
    if (
        row.runtime_digest != binding.runtime
        or row.expires_at < binding.deadline
        or row.expires_at <= timezone.now()
        or row.surface != binding.surface
        or row.provider_id != binding.provider.provider_id
        or row.subject_id != binding.actor.subject_id
        or row.role != binding.actor.role
        or row.auth_epoch != binding.actor.auth_epoch
        or row.browser_digest != binding.browser_digest
        or row.claims_digest != digest(claims(binding.actor))
        or SessionRevocation.objects.filter(session=row).exists()
    ):
        reject()
    if actor is not None and digest(claims(identity(actor))) != row.claims_digest:
        reject()
    if authorize:
        permit(
            binding.authority,
            binding.provider,
            identity(actor or binding.actor),
            "USE",
            resource(row),
        )
        check(binding, actor=actor, lock=lock, authorize=False)
    if (
        binding.deadline <= timezone.now()
        or epoch(binding.authority) != binding.authority_epoch
        or epoch(binding.provider) != binding.directory_epoch
    ):
        reject()
    return row


def recheck(binding, *, lock=False):
    actor = fresh_identity(binding.provider, binding.actor)
    check(binding, actor=actor, lock=lock)
    return replace(actor, valid_until=min(actor.valid_until, binding.deadline))


def rule(binding, actor, target):
    try:
        result = binding.authority.reauthentication(
            **actor_values(binding.provider, actor), operation=OPERATION, resource=resource(target)
        )
    except Exception as exc:
        raise IdentityUnavailable("staff_reauthentication_policy_unavailable") from exc
    if (
        type(result) is not ReauthenticationRule
        or type(result.required) is not bool
        or type(result.max_age_seconds) is not int
        or not 1 <= result.max_age_seconds <= 300
    ):
        reject()
    check(binding, actor=actor, authorize=False)
    return result


def target(binding, target_id, action):
    actor = recheck(binding)
    row = get(target_id)
    permit(binding.authority, binding.provider, actor, action, resource(row))
    check(binding, actor=actor, authorize=False)
    return actor, row


@contextmanager
def listing(binding):
    actor = recheck(binding)
    own = check(binding)
    permit(binding.authority, binding.provider, actor, "LIST", resource(own))
    rows = []
    # Finite own-account history. Administrators inspect exact targets only.
    for row in Session.objects.filter(
        provider_id=own.provider_id, subject_id=own.subject_id
    ).order_by("-created_at")[:64]:
        checked(row)
        permit(binding.authority, binding.provider, actor, "READ", resource(row))
        rows.append(
            {
                "id": str(row.id),
                "surface": row.surface,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "current": str(row.id) == binding.id,
                "revoked": SessionRevocation.objects.filter(session=row).exists(),
                "expired": row.expires_at <= timezone.now()
                or row.runtime_digest != runtime_digest(),
            }
        )
    yield rows
    recheck(binding)


def inspect(binding, target_id):
    actor, row = target(binding, target_id, "READ")
    permit(binding.authority, binding.provider, actor, "REVOKE", resource(row))
    if SessionRevocation.objects.filter(session=row).exists():
        reject()
    return row, rule(binding, actor, row)


def authenticate_fresh(binding, *, target_id, credential):
    if connection.in_atomic_block:
        raise IdentityUnavailable("staff_fresh_verifier_outer_boundary_required")
    actor, row = target(binding, target_id, "REVOKE")
    policy = rule(binding, actor, row)
    provider = binding.provider
    if (
        not isinstance(provider, FreshAuthentication)
        or not _ref(getattr(provider, "fresh_method_id", None))
        or type(credential) is not str
        or not 32 <= len(credential) <= 1024
        or not credential.isascii()
        or any(char.isspace() or ord(char) < 33 for char in credential)
    ):
        reject()
    method_id = provider.fresh_method_id
    challenge = secrets.token_hex(32)
    started = timezone.now()
    # This explicit adapter call actively checks the supplied credential; a
    # directory resolve or preexisting login claim cannot supply a fresh proof.
    from . import execution

    success, verified = execution.invoke(provider, credential, challenge=challenge, timeout=20.0)
    if not success:
        raise IdentityUnavailable("staff_reauthentication_unavailable")
    finished = timezone.now()
    if (
        type(verified) is not FreshResult
        or verified.challenge != challenge
        or verified.method_id != method_id
        or provider.fresh_method_id != method_id
        or not isinstance(verified.verified_at, datetime)
        or not timezone.is_aware(verified.verified_at)
        or not started <= verified.verified_at <= finished
        or finished - started > timedelta(seconds=20)
        or claims(identity(verified.identity)) != claims(actor)
    ):
        reject()
    with synthetic_queue_atomic():
        for session_id in sorted({binding.id, str(row.id)}):
            get(session_id, lock=True)
        actor, current = target(binding, target_id, "REVOKE")
        if (
            current.digest != row.digest
            or rule(binding, actor, current) != policy
            or SessionRevocation.objects.filter(session=row).exists()
        ):
            reject()
        proof = create(
            FreshProof,
            session_id=uid(binding.id),
            target_id=row.id,
            operation=OPERATION,
            target_digest=row.digest,
            challenge_digest=digest(challenge),
            authority_digest=digest(binding.authority_epoch),
            directory_digest=digest(binding.directory_epoch),
            method_id=verified.method_id,
            verified_at=verified.verified_at,
            expires_at=min(
                binding.deadline, verified.verified_at + timedelta(seconds=policy.max_age_seconds)
            ),
        )
        recheck(binding)
    return proof


def _append_revocation(target_row, by_row, reason, proof):
    return create(
        SessionRevocation,
        session_id=target_row.id,
        by_session_id=by_row.id,
        reason=reason,
        proof_id=proof.id if proof else None,
    )


def revoke(binding, *, target_id, proof_id="", logout=False):
    with synthetic_queue_atomic():
        for session_id in sorted({binding.id, str(uid(target_id))}):
            get(session_id, lock=True)
        actor, row = target(binding, target_id, "LOGOUT" if logout else "REVOKE")
        current = check(binding, actor=actor)
        if logout and row.id != current.id:
            reject()
        if SessionRevocation.objects.filter(session=row).exists():
            reject()
        policy = rule(binding, actor, row)
        proof = None
        if not logout and (policy.required or proof_id):
            try:
                proof = checked(FreshProof.objects.select_for_update().get(pk=uid(proof_id)))
            except FreshProof.DoesNotExist as exc:
                raise IdentityUnavailable("staff_fresh_proof_required") from exc
            if (
                proof.session_id != current.id
                or proof.target_id != row.id
                or proof.target_digest != row.digest
                or proof.operation != OPERATION
                or proof.method_id != getattr(binding.provider, "fresh_method_id", None)
                or proof.expires_at <= timezone.now()
                or proof.verified_at + timedelta(seconds=policy.max_age_seconds) <= timezone.now()
                or proof.authority_digest != digest(binding.authority_epoch)
                or proof.directory_digest != digest(binding.directory_epoch)
                or ProofUse.objects.filter(proof=proof).exists()
            ):
                reject()
        recheck(binding)
        result = _append_revocation(row, current, "LOGOUT" if logout else "USER_REVOKE", proof)
        if proof:
            create(ProofUse, proof_id=proof.id, revocation_id=result.id)
        # Check current policy/identity even when the operation intentionally
        # revokes this request's own session. Never replay a consumed proof.
        fresh_identity(binding.provider, actor)
        if (
            configured(binding.provider) is not binding.authority
            or epoch(binding.authority) != binding.authority_epoch
            or epoch(binding.provider) != binding.directory_epoch
            or binding.deadline <= timezone.now()
            or binding.runtime != runtime_digest()
        ):
            reject()
        if row.id != current.id:
            check(binding, actor=actor, authorize=False)
    if str(row.id) == binding.id:
        binding.lease.closed_by_request.add(binding.id)
    return result


def audit(*, provider, actor, session_id):
    """Fresh trusted identity plus explicit AUDIT grant; restored rows grant nothing."""
    authority = configured(provider)
    actor = identity(actor)
    before = epoch(authority), epoch(provider)
    fresh_identity(provider, actor)
    row = get(session_id)
    permit(authority, provider, actor, "AUDIT", resource(row))
    result = {
        "session": resource(row),
        "revoked": SessionRevocation.objects.filter(session=row).exists(),
        "proofs": FreshProof.objects.filter(session=row).count(),
        "consumed": ProofUse.objects.filter(proof__session=row).count(),
    }
    fresh_identity(provider, actor)
    if configured(provider) is not authority or before != (epoch(authority), epoch(provider)):
        reject()
    return result
