"""Import permission is separate from library editing, reading and release."""

from abc import ABC, abstractmethod


class ImportAuthority(ABC):
    @abstractmethod
    def projection_epoch(self):
        """Atomic side-effect-free revision covering all grants and their expiry.

        Changing any grant in a callback must change this revision. An unavailable
        or unversioned provider cannot authorize even a staging projection.
        """
        raise NotImplementedError

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, namespace):
        """Return literal True for this exact current case/namespace/action.

        Actions: VIEW, STAGE, MAP, PLAN, REVIEW, APPLY, CANCEL, EXPORT. Library services
        additionally check their own independent VIEW/EDIT policy. REVIEW is a
        technical import/provenance decision, never scholarly approval or release.
        """
        raise NotImplementedError
