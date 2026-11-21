"""Lazy closed hooks and native response pins, including pre-authentication."""

from contextvars import ContextVar
from functools import wraps

from django.apps import apps
from django.conf import settings

from apps.editorial_workbench.reviewer_access import browser_proof
from apps.mufti_review.identity import IdentityUnavailable

SALT = "fatwa.staff-mfa.browser.v1"
_PRESENTATION = ContextVar("fatwa_staff_mfa_presentation", default=None)


def retaining():
    return _PRESENTATION.get() is not None


def retain(check):
    checks = _PRESENTATION.get()
    if checks is not None:
        checks.append(check)


def native(view):
    """Own only HTTP presentation pins; direct service calls need no request lease."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not enabled() or retaining():
            return view(request, *args, **kwargs)
        from django.db import DatabaseError

        from apps.casework_web.guard import denied
        from apps.staff_sessions import integration as session_context

        checks = []
        token = _PRESENTATION.set(checks)
        try:
            # An admitted pre-authentication response needs the same final lease
            # as a full staff response, without creating a staff identity binding.
            session_context.context()
            response = view(request, *args, **kwargs)

            def pure_final():
                for check in tuple(checks):
                    check()

            pure_final()
            session_context.retain_final_guard(
                pure_final, failure=IdentityUnavailable, code="staff_mfa_not_authorized"
            )
            return response
        except IdentityUnavailable:
            return denied("staff_mfa_not_authorized", 403)
        except DatabaseError:
            return denied("staff_mfa_store_unavailable", 503)
        finally:
            _PRESENTATION.reset(token)

    return wrapped


def enabled():
    return getattr(settings, "FATWA_STAFF_MFA_ENABLED", False) is True


def fields():
    if enabled():
        if (
            not apps.is_installed("apps.staff_mfa")
            or getattr(settings, "FATWA_STAFF_SESSIONS_ENABLED", False) is not True
        ):
            raise IdentityUnavailable("staff_mfa_configuration_required")
        return {"mfa_proof"}
    return set()


def binding(request, surface):
    return browser_proof(request, SALT, surface)


def legacy(provider_id, subject_id, *, retain_http=False):
    from .history import assert_legacy

    def current():
        assert_legacy(provider_id, subject_id)

    current()
    if retain_http:
        from apps.staff_sessions import integration as session_context

        session_context.retain_final_guard(
            current, failure=IdentityUnavailable, code="staff_mfa_required"
        )


def issue_cookie(request, values, *, grant, provider, actor, surface):
    if enabled():
        from . import services

        fields()
        services.issuance(grant, provider=provider, actor=actor, surface=surface)
        if grant.challenge.browser_digest != services.digest(binding(request, surface)):
            services.reject()
        values["mfa_proof"] = str(grant.proof.id)
    elif grant is not None:
        raise IdentityUnavailable("staff_mfa_disabled")
    else:
        legacy(provider.provider_id, actor.subject_id, retain_http=True)


def current_cookie(request, values, *, surface):
    if enabled():
        from . import services
        from .models import Proof

        fields()
        try:
            proof = services.checked(
                Proof.objects.select_related("challenge").get(
                    pk=services.sessions.uid(values["mfa_proof"])
                )
            )
        except Proof.DoesNotExist as exc:
            raise IdentityUnavailable("staff_mfa_session_proof_required") from exc
        challenge = services.checked(proof.challenge)
        if challenge.surface != surface or challenge.browser_digest != services.digest(
            binding(request, surface)
        ):
            services.reject()
    else:
        if values.get("mfa_proof"):
            raise IdentityUnavailable("staff_mfa_disabled")
        legacy(values["provider"], values["subject"], retain_http=True)


def before_issue(*, grant, provider, actor, surface):
    if enabled():
        from . import services

        fields()
        services.issuance(grant, provider=provider, actor=actor, surface=surface)
    elif grant is not None:
        raise IdentityUnavailable("staff_mfa_disabled")
    else:
        legacy(provider.provider_id, actor.subject_id)


def attach(session, *, grant, provider, actor, surface):
    if enabled():
        from . import services

        return services.attach(session, grant, provider=provider, actor=actor, surface=surface)


def capture(*, provider, actor, session_id, proof_id):
    if enabled():
        from . import services

        fields()
        return services.capture(
            provider=provider, actor=actor, session_id=session_id, proof_id=proof_id
        )
    if proof_id:
        raise IdentityUnavailable("staff_mfa_disabled")
    legacy(provider.provider_id, actor.subject_id)
    return None


def check(use, *, provider=None, actor=None, authorize=True, lock=False):
    if use is None:
        if enabled():
            raise IdentityUnavailable("staff_mfa_session_proof_required")
        if provider is None or actor is None:
            raise IdentityUnavailable("staff_mfa_legacy_identity_required")
        legacy(provider.provider_id, actor.subject_id)
        return
    if not enabled():
        raise IdentityUnavailable("staff_mfa_disabled")
    from . import services

    return services.check(use, authorize=authorize, lock=lock)
