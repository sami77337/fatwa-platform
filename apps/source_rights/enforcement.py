"""One strict-mode contract shared by source consumers, without policy grants."""

from django.conf import settings

from apps.casework.services import CaseConflict


def required():
    """Only literal False selects legacy mode; malformed configuration denies."""
    flag = getattr(settings, "FATWA_SOURCE_RIGHTS_ENFORCED", False)
    if type(flag) is not bool:
        raise CaseConflict("source_rights_configuration_invalid")
    return flag
