"""Export permission is independent from reading, publication and source licensing."""

from abc import ABC, abstractmethod

from apps.casework.services import CaseConflict


class ExportAuthority(ABC):
    def projection_epoch(self):
        """Atomic, side-effect-free revision of every grant input, including expiry.

        A callback changing another resource's grant must change this revision.
        An unversioned provider cannot authorize an export, preview or download.
        """
        raise CaseConflict("export_policy_snapshot_required")

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        """Literal True only for an exact current principal, case and resource.

        Scope actions VIEW/PREPARE/GENERATE/DOWNLOAD/MANAGE use resource=None.
        EXPORT_RECORD authorizes one exact Resource; EXPORT_SENSITIVE separately
        authorizes transcript/knowledge/private media; EXPORT_MEDIA additionally
        authorizes inclusion of original bytes. Reading never supplies a grant.
        """
        raise NotImplementedError
