"""A separately configured administrative mandate cannot be granted by a template."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Grant:
    valid_until: datetime


class PermissionManagementAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Pure atomic revision of all mandates, candidates, resources and deadlines."""
        raise NotImplementedError

    @abstractmethod
    def subjects(self, *, provider_id, subject_id, auth_epoch, role):
        """A finite tuple of exact existing subject IDs; a choice never grants control."""
        raise NotImplementedError

    @abstractmethod
    def resources(self, *, provider_id, subject_id, auth_epoch, role):
        """Finite exact operational scopes, with no effects, patterns or role defaults."""
        raise NotImplementedError

    @abstractmethod
    def authorize(
        self,
        *,
        provider_id,
        subject_id,
        auth_epoch,
        role,
        operation,
        scope_kind,
        scope_key,
        target_subject,
        target_role,
        resource,
    ):
        """Grant or None for this actual actor and exact change/read.

        ENTER, CREATE_SET, READ_SET, WRITE_SET, READ_USER, WRITE_USER and READ_AUDIT
        are separate administrative mandates. MANAGE_RULE additionally authorizes
        the exact scope/effect, including removed rules and affected users.
        MUFTI and ORGANIZER_ADMIN use the same contract; neither role grants it.
        This authority is external to the managed ledger and never writable by it.
        """
        raise NotImplementedError
