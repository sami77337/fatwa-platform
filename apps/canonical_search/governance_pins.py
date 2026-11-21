"""Pure append-only history pins for dictionary and shadow compositions."""

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases

from .models import ShadowComparison, SynonymDecision, SynonymPreview, SynonymRevision

MODELS = (SynonymRevision, SynonymPreview, SynonymDecision, ShadowComparison)
ACTIONS = frozenset(
    {
        "DICTIONARY_READ",
        "DICTIONARY_EDIT",
        "DICTIONARY_REVIEW",
        "DICTIONARY_USE",
        "SHADOW",
        "SHADOW_READ",
    }
)


def flag():
    value = getattr(settings, "FATWA_SEARCH_GOVERNANCE_ENABLED", False)
    return type(value), value


def enabled():
    if flag() != (bool, True):
        raise cases.CaseConflict("search_governance_disabled")


def require_configured_identity(provider):
    from apps.casework_web.access import RequestDirectory

    configured = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if configured is None or not (
        provider is configured
        or (isinstance(provider, RequestDirectory) and provider._provider is configured)
    ):
        raise cases.CaseConflict("search_governance_current_identity_required")


def history(case_ids):
    return frozenset(
        (model._meta.model_name, str(pk), digest)
        for model in MODELS
        for pk, digest in model.objects.filter(case_id__in=case_ids).values_list("pk", "digest")
    )


class Pins:
    def __init__(self, case_ids):
        self.case_ids, self.configuration = tuple(case_ids), flag()
        self.initial = history(case_ids) if self.configuration == (bool, True) else frozenset()
        self.written, self.deadlines = set(), []

    def wrote(self, row):
        self.written.add((row._meta.model_name, str(row.pk), row.digest))

    def finish(self):
        if flag() != self.configuration:
            raise cases.CaseConflict("search_governance_changed")
        if (
            self.configuration == (bool, True)
            and history(self.case_ids) != self.initial | self.written
        ):
            raise cases.CaseConflict("search_governance_history_changed")
        if any(timezone.now() >= deadline for deadline in self.deadlines):
            raise cases.CaseConflict("search_dictionary_expired")
