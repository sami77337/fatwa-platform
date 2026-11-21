"""Coherent private-media policy snapshots across composed case projections.

No permissions or content are cached. Policies supply an atomic, side-effect-free
version of every media authorization input; an unversioned policy fails closed.
Case locks still serialize authoritative mutation. Epoch checks supplement exact
READ_MEDIA/CITE, identity, source and expiry checks rather than replacing them.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from django.conf import settings
from django.utils import timezone

_SCOPES = ContextVar("casework_media_policy_scopes", default=())
_DEADLINES = ContextVar("casework_media_projection_deadlines", default=())


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


def pin_media_deadline(deadline):
    """Retain validated media deadlines through every enclosing epoch read.

    This stores only a conservative expiry, not permission or bytes. No policy
    callback is invoked here or after the final boundary clock check.
    """
    from .services import CaseConflict

    if not isinstance(deadline, datetime) or timezone.is_naive(deadline):
        raise CaseConflict("timed_grant_expiry_required")
    scopes = _DEADLINES.get()
    if not _SCOPES.get():
        raise CaseConflict("media_projection_boundary_required")
    for scope in scopes:
        scope[0] = deadline if scope[0] is None else min(scope[0], deadline)


class MediaProjectionPin:
    """Retain the same pure policy/deadline checks after an inner context exits."""

    def __init__(self, scope, earliest, scan_pin):
        self.scope, self.earliest, self.scan_pin = scope, earliest, scan_pin

    def final_pins(self):
        from .services import CaseConflict

        if self.scope:
            policy, epoch = self.scope
            if (
                getattr(settings, "FATWA_RESEARCH_WORKSPACE_RIGHTS", None) is not policy
                or _epoch(policy) != epoch
            ):
                raise CaseConflict("media_policy_changed")
        # The final atomic epoch lookup may span a deadline without changing it.
        # This runs inside _staff_case transaction.atomic, before commit/return.
        if self.earliest[0] is not None and self.earliest[0] <= timezone.now():
            raise CaseConflict("timed_grant_expired")
        self.scan_pin.check()


@contextmanager
def media_projection_boundary(*, retain_deadlines=True):
    """Check once at each enclosing return boundary, without another permits loop."""
    scope = []
    token = _SCOPES.set((*_SCOPES.get(), scope))
    earliest = [None]
    deadline_token = _DEADLINES.set(
        (*_DEADLINES.get(), earliest) if retain_deadlines else _DEADLINES.get()
    )
    from apps.upload_security.services import projection as scan_projection

    try:
        with scan_projection() as scan_pin:
            pin = MediaProjectionPin(scope, earliest, scan_pin)
            yield pin
            pin.final_pins()
    finally:
        _DEADLINES.reset(deadline_token)
        _SCOPES.reset(token)
