"""Explicit operational adapter; no domain or administrative authority is inferred."""

from django.conf import settings

from apps.operational_workspace import identity
from apps.operational_workspace.authority import OperationalAuthority

from . import catalog, store


class StoredOperationalAuthority(OperationalAuthority):
    def projection_epoch(self):
        store.enabled()
        # Pure: no authorize/resolve callbacks. The existing operational Guard
        # retains this full ledger pin after every other domain callback.
        return catalog.digest(store.fingerprint())

    def _grant(self, *, provider_id, subject_id, role, auth_epoch, case_ref, action, resource):
        store.enabled()
        directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        if getattr(directory, "provider_id", None) != provider_id:
            return None
        actor = identity.resolve(directory, subject_id, case_ref=case_ref)
        if actor.role != role or actor.auth_epoch != auth_epoch:
            return None
        return store.grant(
            actor,
            provider_id,
            {
                "domain": catalog.DOMAIN,
                "case_ref": case_ref,
                "action": action,
                "resource": resource,
            },
        )

    def permits(self, **values):
        try:
            return self._grant(**values) is not None
        except catalog.PermissionDenied:
            return False

    def grant_deadline(self, **values):
        return self._grant(**values)
