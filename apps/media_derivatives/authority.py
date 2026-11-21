"""Explicit derivative permission seam; no role or successful-source grant default."""

from abc import ABC, abstractmethod


class DerivativeAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Pure atomic version of every authorization input; change on revocation."""
        raise NotImplementedError

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, task, source):
        """Exact CREATE, EXECUTE, READ, DOWNLOAD, RETRY or CANCEL grant for this owned source.

        EXECUTE independently authorizes bounded local processing on behalf of the
        currently resolved submitter. This is not a machine identity or AI grant.
        Source READ rights, privacy and scan still apply. Callbacks must serialize
        authoritative revocation with the canonical case lock.
        """
        raise NotImplementedError

    @abstractmethod
    def grant_deadline(
        self, *, provider_id, subject_id, auth_epoch, case_ref, action, task, source
    ):
        """Explicit timezone-aware expiry of this exact grant, at most one hour ahead.

        Return no deadline when the exact grant is absent. A later grant or a
        longer actor/session expiry cannot extend an already used permission.
        This callback obeys the same atomic policy revision as permits().
        """
        raise NotImplementedError
