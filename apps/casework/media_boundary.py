"""Coherent private-media policy snapshots across composed case projections.

No permissions or content are cached. Policies supply an atomic, side-effect-free
version of every media authorization input; an unversioned policy fails closed.
Case locks still serialize authoritative mutation. Epoch checks supplement exact
READ_MEDIA/CITE, identity, source and expiry checks rather than replacing them.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

_SCOPES = ContextVar("casework_media_policy_scopes", default=())


def _epoch(policy):
    from .services import CaseConflict

    try:
        value = policy.media_projection_epoch()
        if type(value) is not str or not value or len(value) > 1000:
            raise ValueError
        return value
    except Exception as exc:
        raise CaseConflict("media_policy_snapshot_required") from exc


def pin_media_policy(policy):
    """Enroll before the first permits/deadline callback in every outer scope."""
    from .services import CaseConflict

    scopes = _SCOPES.get()
    if not scopes:
        raise CaseConflict("media_projection_boundary_required")
    epoch = _epoch(policy)
    for scope in scopes:
        if scope and (scope[0] is not policy or scope[1] != epoch):
            raise CaseConflict("media_policy_changed")
        if not scope:
            scope.extend((policy, epoch))


@contextmanager
def media_projection_boundary():
    """Check once at each enclosing return boundary, without another permits loop."""
    from .services import CaseConflict

    scope = []
    token = _SCOPES.set((*_SCOPES.get(), scope))
    try:
        yield
        if scope:
            policy, epoch = scope
            if (
                getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None) is not policy
                or _epoch(policy) != epoch
            ):
                raise CaseConflict("media_policy_changed")
    finally:
        _SCOPES.reset(token)
