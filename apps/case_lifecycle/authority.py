"""Lifecycle permission never supplies identity, case access or delivery proof."""

from abc import ABC, abstractmethod


class LifecycleAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Atomic, side-effect-free revision of every current grant input.

        Any grant, revocation, scope, expiry or policy change advances this value.
        Returning a value must never itself change policy or application state.
        """
        raise NotImplementedError

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        """Literal True for this exact scoped MUFTI, action and resource snapshot.

        READ, CLOSE, REOPEN, ARCHIVE, RESTORE and CLOSE_WITHOUT_DELIVERY are
        independent. `resource` contains exact case/evidence/lifecycle versions
        and current state; no wildcard role or hierarchy is inferred.
        CLOSE_WITHOUT_DELIVERY additionally requires a human form choice and
        is never accepted while any current delivery plan exists.
        """
        raise NotImplementedError
