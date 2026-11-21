"""A saved factor vetoes legacy authentication even when MFA is unconfigured.

This reader imports no MFA/session models so older settings can still detect
existing enrollment tables after an app was removed from INSTALLED_APPS. It grants
nothing and never reads ciphertext or recovery material.
"""

from django.apps import apps
from django.conf import settings
from django.db import DatabaseError, connection

from apps.mufti_review.identity import IdentityUnavailable, _ref


def assert_legacy(provider_id, subject_id):
    if (
        getattr(settings, "FATWA_STAFF_MFA_ENABLED", False) is True
        or not _ref(provider_id)
        or not _ref(subject_id)
        or connection.vendor != "postgresql"
    ):
        raise IdentityUnavailable("staff_mfa_required")
    try:
        with connection.cursor() as cursor:
            if not apps.is_installed("apps.staff_mfa"):
                cursor.execute(
                    "SELECT to_regclass('public.staff_mfa_account') IS NOT NULL, "
                    "to_regclass('public.staff_mfa_factor') IS NOT NULL"
                )
                account_exists, factor_exists = cursor.fetchone()
                if not account_exists and not factor_exists:
                    return
                if not account_exists or not factor_exists:
                    raise IdentityUnavailable("staff_mfa_history_required")
            # PostgreSQL migrations in this development composition own these
            # public tables. Qualifying them prevents a changed search_path from
            # hiding saved enrollment. Any saved factor, including an abandoned
            # enrollment or a revoked generation, is a veto; it is never a grant.
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM public.staff_mfa_account AS account "
                "JOIN public.staff_mfa_factor AS factor ON factor.account_id=account.id "
                "WHERE account.provider_id=%s AND account.subject_id=%s)",
                (provider_id, subject_id),
            )
            if cursor.fetchone()[0]:
                raise IdentityUnavailable("staff_mfa_required")
    except DatabaseError as exc:
        raise IdentityUnavailable("staff_mfa_history_unavailable") from exc
