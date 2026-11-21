"""Retain canonical source, current grants and configured keys through final render."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.case_citations.models import AnswerCitation
from apps.case_citations.services import _projection_expiry_guard
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvidence, CaseSource
from apps.casework_web.access import RequestDirectory
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.experimental_publication.authority import PublicationAuthority
from apps.platform_recovery.integration import mutation_context
from apps.precise_citations import integration as citations
from apps.public_knowledge import services as knowledge
from apps.reference.models import ReferenceEdition, ReferenceHeading
from apps.research_library import services as library
from apps.source_rights.models import SourceRegistration, SourceVersion

from . import profiles
from .authority import DestinationAuthority
from .models import DestinationEvent, DestinationRecord, DestinationVersion
from .signatures import DestinationOutcomeVerifier

_CURRENT = ContextVar("publication_destination_boundary", default=None)


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PUBLICATION_DESTINATIONS_ENABLED", False) is not True
        or getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("publication_destinations_disabled")


def _epoch(value):
    try:
        epoch = value.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("destination_policy_snapshot_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise cases.CaseConflict("destination_policy_snapshot_required")
    return id(value), epoch


def configuration():
    enabled()
    authority = getattr(settings, "FATWA_PUBLICATION_DESTINATIONS_AUTHORITY", None)
    source_authority = getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None)
    verifier = getattr(settings, "FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER", None)
    if (
        not isinstance(authority, DestinationAuthority)
        or not isinstance(source_authority, PublicationAuthority)
        or not isinstance(verifier, DestinationOutcomeVerifier)
    ):
        raise cases.CaseConflict("destination_current_trust_required")
    return (
        _epoch(authority),
        _epoch(source_authority),
        _epoch(verifier),
        profiles.configured(),
        knowledge._source_configuration(),
    )


def history(case_id):
    return (
        list(DestinationRecord.objects.filter(case_id=case_id).order_by("pk").values()),
        list(DestinationVersion.objects.filter(record__case_id=case_id).order_by("pk").values()),
        list(
            DestinationEvent.objects.filter(version__record__case_id=case_id)
            .order_by("pk")
            .values()
        ),
    )


def canonical(case_ids):
    registered = SourceVersion.objects.filter(
        pk__in=SourceRegistration.objects.filter(case_id__in=case_ids).values("source_id")
    )
    citations = AnswerCitation.objects.filter(answer__case_id__in=case_ids)
    heading_ids = set(registered.values_list("heading_id", flat=True)) | set(
        citations.values_list("heading_id", flat=True)
    )
    headings = ReferenceHeading.objects.filter(pk__in=heading_ids)
    return (
        knowledge._canonical(case_ids),
        list(AnswerRevision.objects.filter(case_id__in=case_ids).order_by("pk").values()),
        list(CaseDecision.objects.filter(case_id__in=case_ids).order_by("pk").values()),
        list(CaseEvidence.objects.filter(case_id__in=case_ids).order_by("pk").values()),
        list(CaseSource.objects.filter(case_id__in=case_ids).order_by("pk").values()),
        list(citations.order_by("pk").values()),
        list(registered.order_by("pk").values()),
        list(headings.order_by("pk").values()),
        list(
            ReferenceEdition.objects.filter(pk__in=headings.values("edition_id"))
            .order_by("pk")
            .values()
        ),
    )


class Guard:
    def __init__(self, case_id, locked, provider):
        self.case_id, self.locked = case_id, locked
        self.case = locked[case_id]
        self.config = configuration()
        self.authority = settings.FATWA_PUBLICATION_DESTINATIONS_AUTHORITY
        self.verifier = settings.FATWA_PUBLICATION_DESTINATIONS_PROVIDER_VERIFIER
        self.directory = settings.FATWA_CASEWORK_IDENTITY_PROVIDER
        self.provider = provider
        if not (
            provider is self.directory
            or isinstance(provider, RequestDirectory)
            and provider._provider is self.directory
        ):
            raise cases.CaseConflict("destination_configured_identity_required")
        self.directory_pin = library.identity_snapshot(self.directory)
        self.provider_pin = library.identity_snapshot(provider)
        self.source_rows = canonical(locked)
        self.rows = history(case_id)
        self.permissions, self.identities, self.deadlines, self.sources = [], {}, [], {}

    def actor(self, provider, subject, recorded=None, *, editorial=False):
        actor = self.resolve(provider, subject, editorial=editorial)
        if recorded is not None and (
            provider.provider_id != recorded.provider_id or actor.auth_epoch != recorded.auth_epoch
        ):
            raise cases.CaseConflict("destination_recorded_actor_changed")
        key = id(provider), subject, editorial
        old = self.identities.get(key)
        if old is not None and library._actor(old[1]) != library._actor(actor):
            raise cases.CaseConflict("destination_identity_changed")
        self.identities[key] = provider, actor, editorial
        self.deadlines.append(actor.valid_until)
        return actor

    def resolve(self, provider, subject, *, editorial=False):
        if editorial:
            from apps.operational_workspace.identity import resolve

            return resolve(provider, subject, case_ref=self.case.public_ref)
        return cases._identity(provider, subject, self.case)

    def _permission(self, values, *, required=True):
        try:
            allowed = self.authority.permits(**values)
            deadline = self.authority.grant_deadline(**values) if allowed is True else None
        except Exception as exc:
            raise cases.CaseConflict("destination_authority_unavailable") from exc
        if allowed is not True:
            if required:
                raise cases.CaseConflict("destination_action_denied")
            return None
        now = timezone.now()
        if (
            not isinstance(deadline, datetime)
            or timezone.is_naive(deadline)
            or not now < deadline <= now + timedelta(hours=1)
        ):
            raise cases.CaseConflict("destination_finite_grant_required")
        self.deadlines.append(deadline)
        return deadline

    def permit(
        self, provider, actor, destination, action, identifier="", digest="", *, required=True
    ):
        values = dict(
            provider_id=provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=self.case.public_ref,
            destination=destination,
            action=action,
            resource_id=str(identifier),
            resource_sha256=digest,
        )
        deadline = self._permission(values, required=required)
        if deadline is not None and values not in self.permissions:
            self.permissions.append(values)
        if deadline is not None and identifier and action != "WITHDRAW":
            from apps.data_privacy.services import PrivacyDenied

            source_id = (
                identifier
                if action == "SELECT"
                else DestinationVersion.objects.filter(
                    pk=cases._uuid(identifier), record__case=self.case
                )
                .values_list("source_id", flat=True)
                .first()
            )
            if source_id is None:
                raise cases.CaseConflict("destination_version_unavailable")
            try:
                privacy.staff(
                    "PUBLICATION",
                    source_id,
                    provider=provider,
                    actor=actor,
                    action="PUBLISH"
                    if action in {"SELECT", "APPROVE", "PREPARE", "OBSERVE"}
                    else "READ",
                )
            except PrivacyDenied:
                if required:
                    raise
                return None
        return deadline

    def callbacks(self):
        from .services import source_current

        for source in tuple(self.sources.values()):
            source_current(self, source)
        for values in tuple(self.permissions):
            self._permission(values)
        for provider, actor, editorial in tuple(self.identities.values()):
            current = self.resolve(provider, actor.subject_id, editorial=editorial)
            if library._actor(current) != library._actor(actor):
                raise cases.CaseConflict("destination_identity_changed")
            self.deadlines.append(current.valid_until)

    def pure(self):
        if (
            configuration() != self.config
            or settings.FATWA_CASEWORK_IDENTITY_PROVIDER is not self.directory
            or library.identity_snapshot(self.directory) != self.directory_pin
            or library.identity_snapshot(self.provider) != self.provider_pin
            or canonical(self.locked) != self.source_rows
            or history(self.case_id) != self.rows
        ):
            raise cases.CaseConflict("destination_projection_changed")
        if any(value <= timezone.now() for value in self.deadlines):
            raise cases.CaseConflict("destination_current_grant_expired")

    def before_write(self):
        self.callbacks()
        self.pure()

    def written(self):
        # Only the intended local append may advance this boundary's baseline.
        self.rows = history(self.case_id)


@mutation_context
@privacy.contextual
@contextmanager
def scope(*, case_id, subject_id, provider, synthetic_fixtures_only=False, **unused):
    enabled()
    cases._guard(synthetic_fixtures_only)
    identifier = cases._uuid(case_id)
    existing = _CURRENT.get()
    if existing is not None:
        if identifier != existing.case_id or provider is not existing.provider:
            raise cases.CaseConflict("destination_nested_scope_changed")
        actor = existing.actor(provider, subject_id)
        with privacy.staff_case(existing.case, actor, provider):
            yield existing, actor
        return
    with synthetic_queue_atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        identifiers = citations.prelock_cases({identifier})
        locked = {
            row.pk: row
            for row in Case.objects.filter(pk__in=identifiers).order_by("pk").select_for_update()
        }
        if identifier not in locked:
            raise cases.CaseConflict("destination_case_unavailable")
        guard = Guard(identifier, locked, provider)
        actor = guard.actor(provider, subject_id)
        with (
            privacy.staff_case(guard.case, actor, provider),
            cases._answer_use_boundary(),
            _projection_expiry_guard(),
        ):
            cases._verify(guard.case)
            guard.permit(provider, actor, "", "READ")
            guard.pure()
            token = _CURRENT.set(guard)
            try:
                yield guard, actor
                guard.callbacks()
            finally:
                _CURRENT.reset(token)
        # Exact-source permission/byte callbacks are now complete; no callback follows.
        guard.pure()
