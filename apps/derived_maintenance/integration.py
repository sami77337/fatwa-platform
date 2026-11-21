"""Current derivative veto. A clearance never becomes permission to use a source."""

from dataclasses import dataclass

from . import store
from .catalog import DerivedDenied


@dataclass
class Use:
    config: tuple
    saved: object

    def final_pins(self):
        if store.configuration() != self.config:
            raise DerivedDenied("derived_configuration_changed")
        if self.saved is None:
            if store.configured() is not None:
                raise DerivedDenied("derived_configuration_changed")
        else:
            self.saved.final_pins()


def cleared(kind, identifier):
    saved = store.snapshot()
    use = Use(store.configuration(), saved)
    use.final_pins()
    from apps.data_privacy.services import SCOPES
    from apps.staff_sessions.integration import retain_final_guard

    for guard in SCOPES.get():
        guard.retained_derivatives.append(use)
    retain_final_guard(use.final_pins, failure=DerivedDenied, code="derived_response_unavailable")
    return saved is not None and (kind, str(identifier)) in saved.cleared
