"""Explicit case-scoped reporting grants, independent of content-editing rights."""

from abc import ABC, abstractmethod


class ContentReportAuthority(ABC):
    def projection_epoch(self):
        """Atomic, side-effect-free revision covering ALL reporting grant inputs.

        It must change on any permission change, including expiry and changes
        made from a permits callback. An unversioned policy cannot authorize a
        composed report projection, source submission, or staff render.
        """
        from apps.casework.services import CaseConflict

        raise CaseConflict("report_policy_snapshot_required")

    @abstractmethod
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, target_kind):
        """Return literal True for READ, SUBMIT, TRIAGE or LINK on this exact case."""
        raise NotImplementedError
