from abc import ABC, abstractmethod


class TaxonomyAuthority(ABC):
    """Current exact human authority; no final religious tree acceptance implied."""

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        raise NotImplementedError

    def projection_epoch(self):
        """Atomic pure revision including current permission and expiry inputs."""
        raise NotImplementedError
