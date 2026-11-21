"""Current operational grants do not grant scholarly approval or account administration."""

from abc import ABC, abstractmethod


class OperationalAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Atomic pure revision of all grants, overrides, revocations and expiry inputs."""
        raise NotImplementedError

    @abstractmethod
    def permits(self, *, provider_id, subject_id, role, auth_epoch, case_ref, action, resource):
        """Literal True for this actual actor and exact action/case/resource only.

        READ_QUEUE, READ_CASE, READ_METADATA, READ_DELIVERY, READ_PUBLICATION,
        READ_TRANSCRIPT and READ_CAPABILITY are independent read grants. No grant
        here may create/approve a scholarly answer, edit its original, publish,
        send, assign a staff role or administer any policy.

        The separately default-off internal-notes feature accepts independent
        READ_INTERNAL_NOTES and ADD_INTERNAL_NOTE grants. ADD permits only an
        append-only internal note with unchanged server-copied tags and types;
        it does not confer read access or any scholarly or metadata edit right.
        """
        raise NotImplementedError

    @abstractmethod
    def grant_deadline(self, **values):
        """Aware UTC deadline of that exact current grant; never an implied grant."""
        raise NotImplementedError
