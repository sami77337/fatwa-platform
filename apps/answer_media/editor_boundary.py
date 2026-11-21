"""Versioned identity/configuration pins for new editor compositions."""

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case


def identity_snapshot(provider):
    """Pin the directory without loading an optional library application's models.

    Answer integrity is checked by older casework profiles too. Those profiles
    intentionally have no research-library schema, even when media flags are off.
    The enhanced editor still requires the same strict pure revision contract.
    """
    method = getattr(provider, "projection_epoch", None)
    try:
        value = method() if callable(method) else None
    except Exception as exc:
        raise cases.CaseConflict("answer_editor_identity_snapshot_required") from exc
    if type(value) is not str or not 1 <= len(value) <= 131072:
        raise cases.CaseConflict("answer_editor_identity_snapshot_required")
    return id(provider), provider.provider_id, value


def head(case_id):
    return tuple(
        Case.objects.filter(pk=case_id).values_list(
            "revision", "evidence_version", "answer_revision", "approved_answer_id", "stage"
        )
    )


class EditorBoundary:
    def __init__(self, provider):
        self.provider = provider
        self.identity = identity_snapshot(provider)
        self.flags = tuple(
            (type(value), value)
            for value in (
                getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", None),
                getattr(settings, "FATWA_ANSWER_LINKS_ENABLED", None),
                getattr(settings, "FATWA_ANSWER_RELATED_ENABLED", None),
                getattr(settings, "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED", None),
            )
        )
        self.directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        self.storage = getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)

    def check(self, actor=None):
        flags = tuple(
            (type(value), value)
            for value in (
                getattr(settings, "FATWA_ANSWER_MEDIA_ENABLED", None),
                getattr(settings, "FATWA_ANSWER_LINKS_ENABLED", None),
                getattr(settings, "FATWA_ANSWER_RELATED_ENABLED", None),
                getattr(settings, "FATWA_ANSWER_MEDIA_PRIVATE_ENABLED", None),
            )
        )
        if (
            identity_snapshot(self.provider) != self.identity
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None) is not self.storage
            or flags != self.flags
            or (actor is not None and timezone.now() >= actor.valid_until)
        ):
            raise cases.CaseConflict("answer_editor_projection_changed")
