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
    from apps.data_privacy.services import SCOPES

    use = Use(store.configuration(), saved, target)
    # snapshot() has just verified the empty, unconfigured store. There is no
    # authority callback or source access between that check and retaining it.
    # Its enclosing projection checks the absence again after the actual use;
    # avoid a second immediate identical SQL read, not a current-use check.
    if saved is not None or not SCOPES.get():
        use.final_pins()

    for guard in SCOPES.get():
        # In an unconfigured, empty store there is no target-specific state to
        # pin. Retain one identical absence check per enclosing projection. Each
        # source admission still reads the current store, and that retained
        # check still rejects newly recorded policy after the final callbacks.
        if saved is None and any(
            previous.saved is None and previous.config == use.config
            for previous in guard.retained_suppression
        ):
            continue
        guard.retained_suppression.append(use)
    return use
