"""Request-local references; no identity fields, implicit role grants or background lease."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from django.conf import settings
from django.db import connection

from apps.mufti_review.identity import IdentityUnavailable

_CURRENT = ContextVar("fatwa_staff_session_context", default=None)


@dataclass
class Lease:
    active: bool = True
    bindings: dict = field(default_factory=dict)
    closed_by_request: set = field(default_factory=set)
    final_guards: list = field(default_factory=list)


class ResponseProjectionDenied(Exception):
    """An admitted response was invalidated after its domain middleware ended."""


def retain_final_guard(check, *, failure, code):
    """Retain a pure check until after every final session authority callback."""
    if enabled():
        context().final_guards.append((check, failure, code))


def check_final_guards(lease):
    for check, failure, code in lease.final_guards:
        try:
            check()
        except failure as exc:
            raise ResponseProjectionDenied(code) from exc


def enabled():
    return getattr(settings, "FATWA_STAFF_SESSIONS_ENABLED", False) is True


@contextmanager
def request_context(lease=None, *, close=True):
    lease = lease or Lease()
    token = _CURRENT.set(lease)
    try:
        yield lease
    finally:
        _CURRENT.reset(token)
        if close:
            lease.active = False


def context():
    lease = _CURRENT.get()
    if lease is None or not lease.active:
        raise IdentityUnavailable("staff_session_request_context_required")
    return lease


def fields():
    from apps.staff_mfa import integration as mfa

    return ({"session_id"} if enabled() else set()) | mfa.fields()


def issue_cookie(request, values, provider, actor, *, surface, deadline, mfa_grant=None):
    from apps.staff_mfa import integration as mfa

    mfa.issue_cookie(request, values, grant=mfa_grant, provider=provider, actor=actor, surface=surface)
    if enabled():
        from . import services

        context()
        values["session_id"] = services.issue(
            provider=provider,
            actor=actor,
            surface=surface,
            browser_binding=values["binding"],
            deadline=deadline,
            mfa_grant=mfa_grant,
        )


def current_cookie(request, values, provider, actor, *, surface, deadline):
    from apps.staff_mfa import integration as mfa

    mfa.current_cookie(request, values, surface=surface)
    if enabled():
        from . import services

        lease = context()
        binding = services.bind(
            provider=provider,
            actor=actor,
            session_id=values["session_id"],
            surface=surface,
            browser_binding=values["binding"],
            deadline=deadline,
            lease=lease,
            mfa_proof=values.get("mfa_proof", ""),
        )
        key = (surface, id(provider), actor.subject_id)
        previous = lease.bindings.get(key)
        if previous and previous != binding:
            # A second authentication in the same request cannot replace a revoked
            # or changed context with a newly inferred grant.
            services.check(previous, actor=actor, authorize=False)
            if (previous.id, previous.authority_epoch, previous.directory_epoch) != (
                binding.id,
                binding.authority_epoch,
                binding.directory_epoch,
            ):
                services.reject()
        lease.bindings[key] = binding


def capture(provider, actor, *, surface):
    if not enabled():
        return None
    from . import services

    binding = context().bindings.get((surface, id(provider), actor.subject_id))
    services.check(binding, actor=actor, authorize=False)
    return binding


def resolve(binding, actor):
    if binding is None:
        if enabled():
            raise IdentityUnavailable("staff_session_binding_required")
        return actor
    from dataclasses import replace

    from . import services

    # A service transaction serializes against revocation on this exact session
    # row. No encompassing request transaction is introduced around AI adapters.
    services.check(binding, actor=actor, lock=connection.in_atomic_block)
    return replace(actor, valid_until=min(actor.valid_until, binding.deadline))


def projection(binding):
    if binding is None:
        if enabled():
            raise IdentityUnavailable("staff_session_binding_required")
        return None
    from . import services

    row = services.check(binding, authorize=False)
    return (
        str(row.id),
        row.digest,
        binding.authority_epoch,
        binding.directory_epoch,
        binding.runtime,
        binding.deadline.isoformat(),
    )
