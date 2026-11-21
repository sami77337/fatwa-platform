"""One current authority, exact source boundaries and retained pure response pins."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.answer_media.editor_boundary import identity_snapshot
from apps.casework import services as cases
from apps.casework.models import Case
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.platform_recovery.integration import mutation_context
from apps.staff_sessions.integration import retain_final_guard
from apps.upload_security import services as scans

from .authority import DerivativeAuthority

SCOPES = ContextVar("media_derivative_response_checks", default=())
FLAGS = (
    "FATWA_MEDIA_DERIVATIVES_ENABLED",
    "FATWA_CASE_ATTACHMENTS_ENABLED",
    "FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED",
    "FATWA_ANSWER_MEDIA_ENABLED",
    "FATWA_RESEARCH_LIBRARY_ENABLED",
    "FATWA_SOURCE_RIGHTS_ENABLED",
    "FATWA_SOURCE_RIGHTS_ENFORCED",
    "FATWA_STAFF_SESSIONS_ENABLED",
    "FATWA_STAFF_MFA_ENABLED",
)


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_MEDIA_DERIVATIVES_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("media_derivatives_disabled")


def epoch(authority):
    try:
        value = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("derivative_policy_snapshot_required") from exc
    if type(value) is not str or not 1 <= len(value) <= 131072:
        raise cases.CaseConflict("derivative_policy_snapshot_required")
    return value


def configuration():
    enabled()
    authority = getattr(settings, "FATWA_MEDIA_DERIVATIVES_AUTHORITY", None)
    if not isinstance(authority, DerivativeAuthority):
        raise cases.CaseConflict("derivative_authority_required")
    return (
        authority,
        epoch(authority),
        tuple(
            (name, type(getattr(settings, name, None)), getattr(settings, name, None))
            for name in FLAGS
        ),
        id(getattr(settings, "FATWA_PRIVATE_MEDIA_STORAGE", None)),
        id(getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)),
        id(getattr(settings, "FATWA_MEDIA_DERIVATIVES_PROCESSOR", None)),
    )


def claims(actor):
    return actor.subject_id, actor.role, actor.active, sorted(actor.case_keys), actor.auth_epoch


class Guard:
    def __init__(self, case, actor, provider, privacy_pin, scan_pin):
        from apps.casework_web.access import RequestDirectory

        actual = provider._provider if type(provider) is RequestDirectory else provider
        if actual is not getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None):
            raise cases.CaseConflict("derivative_current_directory_required")
        self.case, self.actor, self.provider = case, actor, provider
        self.identity = identity_snapshot(provider)
        self.config = configuration()
        self.case_state = list(Case.objects.filter(pk=case.pk).values())
        self.permissions, self.source_checks = [], []
        self.deadline = actor.valid_until
        self.privacy_pin, self.scan_pin = privacy_pin, scan_pin
        self.callbacks = []

    def retain(self):
        from apps.private_media.links import retain_projection

        retain_projection(self.check)
        for checks in SCOPES.get():
            checks.append(self.check)
        if SCOPES.get():
            retain_final_guard(
                self.check, failure=cases.CaseConflict, code="media_derivative_unavailable"
            )

    def permit(self, action, task, source):
        values = dict(
            provider_id=self.provider.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            case_ref=self.case.public_ref,
            action=action,
            task=task,
            source=source,
        )
        self.call(values)
        self.permissions.append(values)

    def call(self, values):
        try:
            allowed = self.config[0].permits(**values)
        except Exception as exc:
            raise cases.CaseConflict("derivative_authority_unavailable") from exc
        if allowed is not True:
            raise cases.CaseConflict("derivative_action_denied")
        try:
            deadline = self.config[0].grant_deadline(**values)
        except Exception as exc:
            raise cases.CaseConflict("derivative_grant_deadline_required") from exc
        now = timezone.now()
        if (
            not isinstance(deadline, datetime)
            or timezone.is_naive(deadline)
            or not now < deadline <= now + timedelta(hours=1)
        ):
            raise cases.CaseConflict("derivative_grant_deadline_required")
        # Every permission used in this scope keeps its original shorter bound.
        # In particular, READ cannot be extended by a later DOWNLOAD/EXECUTE or
        # by the final Session USE callback after the HTTP response is formed.
        self.deadline = min(self.deadline, deadline)

    def finish(self):
        # All possibly mutating callbacks finish before any retained pure check.
        for values in self.permissions:
            self.call(values)
        for callback in self.callbacks:
            callback()
        fresh = cases._identity(self.provider, self.actor.subject_id, self.case)
        if claims(fresh) != claims(self.actor):
            raise cases.CaseConflict("derivative_identity_changed")
        self.deadline = min(self.deadline, fresh.valid_until)
        self.check()

    def check(self):
        if configuration() != self.config or identity_snapshot(self.provider) != self.identity:
            raise cases.CaseConflict("derivative_authority_changed")
        if (
            list(Case.objects.filter(pk=self.case.pk).values()) != self.case_state
            or timezone.now() >= self.deadline
        ):
            raise cases.CaseConflict("derivative_case_or_deadline_changed")
        for check in self.source_checks:
            check()
        self.privacy_pin.final_pins()
        self.scan_pin.check()


@mutation_context
@contextmanager
def boundary(*, case_id, subject_id, provider, synthetic_fixtures_only=False, **unused):
    enabled()
    with (
        privacy.projection(atomic=False) as privacy_pin,
        scans.projection() as scan_pin,
        synthetic_queue_atomic(),
    ):
        with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (
            case,
            actor,
        ):
            guard = Guard(case, actor, provider, privacy_pin, scan_pin)
            yield guard
            guard.finish()
        # Canonical source boundaries may finish after our own service callback.
        # Retain one more pure pass before the actual outer transaction commits.
        guard.check()
        guard.retain()


@contextmanager
def response_projection():
    checks = []
    token = SCOPES.set((*SCOPES.get(), checks))
    try:
        yield checks
        for check in checks:
            check()
    finally:
        SCOPES.reset(token)


class DerivativeResponses:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.casework_web.guard import denied

        try:
            with response_projection() as checks:
                response = self.get_response(request)
                if checks and getattr(response, "streaming", False):
                    raise cases.CaseConflict("derivative_buffered_response_required")
                return response
        except cases.CaseConflict:
            response = denied("media_derivative_unavailable", 404)
            response["Referrer-Policy"] = "no-referrer"
            return response
