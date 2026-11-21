from abc import ABC, abstractmethod


class IdentityAuthority(ABC):
    """Separate current human capabilities; no login, routing, or case grants.

    projection_epoch must be an atomic, pure revision over every grant input,
    including expiration. A recorded decision does not grant its actor access.
    """

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        raise NotImplementedError

    def projection_epoch(self):
        raise NotImplementedError
