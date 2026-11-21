"""A source veto only. It grants neither identity, privacy nor any domain action."""

from dataclasses import dataclass

from . import catalog, store
from .catalog import SuppressionDenied


@dataclass
class Use:
    config: tuple
    saved: object
    target: object

    def final_pins(self):
        if store.configuration() != self.config:
            raise SuppressionDenied("suppression_configuration_changed")
        if self.saved is None:
            if store.configured() is not None:
                raise SuppressionDenied("suppression_configuration_changed")
            return
        self.saved.final_pins()
        if catalog.target(self.target.kind, self.target.identifier) != self.target:
            raise SuppressionDenied("suppression_source_changed")


def require(kind, identifier):
    saved = store.snapshot()
    target = None
    if saved is not None:
        target = catalog.target(kind, str(identifier))
        keys = {(kind, target.identifier)}
        if target.case_id:
            keys.add(("CASE", target.case_id))
        for key in keys:
            current = saved.heads.get(key)
            if current and current["state"] == "SOFT_DELETED":
                raise SuppressionDenied("suppression_material_unavailable")
        current = saved.heads.get((kind, target.identifier))
        if current and current["source_digest"] != target.source_digest:
            raise SuppressionDenied("suppression_source_changed")
    use = Use(store.configuration(), saved, target)
    use.final_pins()
    from apps.data_privacy.services import SCOPES

    for guard in SCOPES.get():
        guard.retained_suppression.append(use)
    return use
