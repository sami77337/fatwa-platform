"""A separately supplied administrative mandate, never a scholarly permission."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Grant:
    valid_until: datetime


class SuppressionAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Pure atomic revision of all grants, resource choices and deadlines."""
        raise NotImplementedError

    @abstractmethod
    def resources(self, *, provider_id, subject_id, auth_epoch, role):
        """Finite tuple of (catalog kind, exact UUID); selection grants nothing."""
        raise NotImplementedError

    @abstractmethod
    def authorize(self, *, provider_id, subject_id, auth_epoch, role, action, resource):
        """ENTER / READ_AUDIT / SOFT_DELETE / RESTORE / RECONCILE, separately.

        Resource is the exact source pin and current suppression state. Neither
        MUFTI nor ORGANIZER_ADMIN receives an implicit grant. Reconciliation is
        a separate action for each missing immutable decision and its source.
        """
        raise NotImplementedError
