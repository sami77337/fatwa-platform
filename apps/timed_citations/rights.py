"""Expiry-aware extension of the existing configured ResearchRights policy.

No rights database or implicit grant. Existing media policies without exact CITE
and expiry evidence remain unsupported/closed for timed references.
"""

from abc import abstractmethod

from apps.research_workspace.rights import ResearchRights


class TimedMediaRights(ResearchRights):
    @abstractmethod
    def grant_deadline(self, *, provider_id, subject_id, auth_epoch, case_ref, action, resource):
        """Aware datetime: conservative expiry for this exact permitted grant.

        Revocation and changes must serialize with the caller's canonical case
        lock. Return None if no verifiable current expiry can be supplied.
        This method supplements, never replaces, permits().
        """
        raise NotImplementedError
