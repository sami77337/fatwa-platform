from abc import ABC, abstractmethod


class ScheduleAuthority(ABC):
    @abstractmethod
    def permits(
        self,
        *,
        provider_id,
        subject_id,
        auth_epoch,
        case_ref,
        action,
        edition_id,
        edition_sha256,
        target,
        scheduled_at,
    ):
        """Literal True for this current actor, exact edition, destination and UTC time."""
        raise NotImplementedError

    @abstractmethod
    def projection_epoch(self):
        """Pure revision of current scheduling grants; never a stored durable grant."""
        raise NotImplementedError
