"""One graph-first case lock boundary, retained through all source/render callbacks."""

import json
import os
from contextlib import ExitStack, contextmanager
from hashlib import sha256

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseDecision
from apps.delivery_queue.services import _canonical, synthetic_queue_atomic
from apps.mufti_review.identity import resolve_identity
from apps.platform_recovery.integration import mutation_context
from apps.research_library import services as library

from .authority import CitationAuthority
from .models import CitationAnchor, CitationReview, CitationSet


def digest(value):
    return sha256(_canonical(value)).hexdigest()


def body(row):
    return library._body(row)


def seal(row):
    row.canonical_payload = _canonical(body(row)).decode()
    row.digest = sha256(row.canonical_payload.encode()).hexdigest()
    row.save(force_insert=True)
    return row


def verify(row):
    if (
        json.loads(row.canonical_payload) != body(row)
        or sha256(row.canonical_payload.encode()).hexdigest() != row.digest
    ):
        raise cases.CaseConflict("precise_citation_integrity")


def enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_PRECISE_CITATIONS_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("precise_citations_disabled")


def policy():
    enabled()
    authority = getattr(settings, "FATWA_PRECISE_CITATIONS_AUTHORITY", None)
    if not isinstance(authority, CitationAuthority):
        raise cases.CaseConflict("precise_citation_authority_required")
    try:
        epoch = authority.projection_epoch()
    except Exception as exc:
        raise cases.CaseConflict("precise_citation_epoch_required") from exc
    if type(epoch) is not str or not 1 <= len(epoch) <= 131072:
        raise cases.CaseConflict("precise_citation_epoch_required")
    return authority, epoch


def dependency_case_ids(case_ids):
    """Pure bounded closure. No source content or authority callbacks."""
    selected = {cases._uuid(value) for value in case_ids}
    for _ in range(65):
        targets = set(
            CitationAnchor.objects.filter(
                citation_set__answer__case_id__in=selected, source_case__isnull=False
            ).values_list("source_case_id", flat=True)
        )
        if targets <= selected:
            return selected
        selected |= targets
        if len(selected) > 64:
            break
    raise cases.CaseConflict("precise_citation_scope_bound")


def lock_dependencies(case_id):
    """Call inside the outer queue transaction BEFORE any canonical case lock."""
    if not connection.in_atomic_block:
        raise cases.CaseConflict("precise_citation_transaction_required")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
    identifiers = dependency_case_ids([case_id])
    return {
        row.pk: row
        for row in Case.objects.filter(pk__in=identifiers).order_by("pk").select_for_update()
    }


def fingerprint(case_ids):
    return (
        list(Case.objects.filter(pk__in=case_ids).order_by("pk").values()),
        list(
            AnswerRevision.objects.filter(case_id__in=case_ids)
            .order_by("pk")
            .values_list("pk", "text_sha256", "revision", "evidence_version")
        ),
        list(CaseDecision.objects.filter(case_id__in=case_ids).order_by("pk").values()),
        list(CitationSet.objects.filter(answer__case_id__in=case_ids).order_by("pk").values()),
        list(
            CitationAnchor.objects.filter(citation_set__answer__case_id__in=case_ids)
            .order_by("pk")
            .values()
        ),
        list(
            CitationReview.objects.filter(citation_set__answer__case_id__in=case_ids)
            .order_by("pk")
            .values()
        ),
    )


class Guard:
    def __init__(self, provider, subject, locked, stack, identity_state):
        self.provider, self.subject, self.locked, self.stack = provider, subject, locked, stack
        self.identity_state = identity_state
        self.directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
        self.directory_state = library.identity_snapshot(self.directory)
        self.authority, self.epoch = policy()
        self.canonical = {key: fingerprint([key]) for key in locked}
        self.permissions, self.actors, self.libraries, self.media = [], {}, {}, []
        self.deadlines = []

    def actor(self, case_id):
        row = self.locked.get(cases._uuid(case_id))
        if row is None:
            raise cases.CaseConflict("precise_citation_case_unavailable")
        actor = cases._identity(self.provider, self.subject, row)
        self.actors[row.pk] = actor
        self.deadlines.append(actor.valid_until)
        return row, actor

    def permit(self, case_id, action, kind="ANSWER", identifier="", source_digest=""):
        row, actor = self.actor(case_id)
        values = dict(
            provider_id=self.provider.provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
            case_ref=row.public_ref,
            action=action,
            kind=kind,
            resource_id=str(identifier),
            resource_digest=source_digest,
        )
        self.call(values)
        if values not in self.permissions:
            self.permissions.append(values)
        return row, actor

    def call(self, values):
        try:
            permitted = self.authority.permits(**values)
        except Exception as exc:
            raise cases.CaseConflict("precise_citation_authority_unavailable") from exc
        if permitted is not True:
            raise cases.CaseConflict("precise_citation_denied")

    def base(self, case_id):
        self.actor(case_id)
        return dict(
            case_id=case_id,
            subject_id=self.subject,
            provider=self.provider,
            synthetic_fixtures_only=True,
        )

    def library(self, case_id):
        key = str(case_id)
        if key not in self.libraries:
            self.stack.enter_context(library.staff_boundary(**self.base(case_id)))
            self.libraries[key] = library._SCOPES.get()[-1]
        return self.base(case_id)

    def written(self, case_id):
        """Freeze the intentional canonical/ledger write BEFORE projection callbacks."""
        key = cases._uuid(case_id)
        self.canonical[key] = fingerprint([key])
        for boundary in self.libraries.values():
            if boundary.case.pk == key:
                boundary.case_state = list(Case.objects.filter(pk=key).values())

    def callbacks(self):
        for values in self.permissions:
            self.call(values)
        for identifier, actor in self.actors.items():
            fresh = cases._identity(self.provider, self.subject, self.locked[identifier])
            if library._actor(fresh) != library._actor(actor):
                raise cases.CaseConflict("precise_citation_identity_changed")
            self.deadlines.append(fresh.valid_until)

    def verify_bytes(self):
        for boundary in self.libraries.values():
            boundary.check_files()
        for part in self.media:
            from apps.answer_media.services import raw_for_part

            if sha256(raw_for_part(part)).hexdigest() != part.sha256:
                raise cases.CaseConflict("precise_citation_original_changed")

    def final_pins(self, *, verify_files=True):
        if verify_files:
            self.verify_bytes()
        for boundary in self.libraries.values():
            boundary.final_pins()
        current, epoch = policy()
        if (
            current is not self.authority
            or epoch != self.epoch
            or library.identity_snapshot(self.provider) != self.identity_state
            or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not self.directory
            or library.identity_snapshot(self.directory) != self.directory_state
            or any(fingerprint([key]) != value for key, value in self.canonical.items())
        ):
            raise cases.CaseConflict("precise_citation_projection_changed")
        if any(end <= timezone.now() for end in self.deadlines):
            raise cases.CaseConflict("precise_citation_expired")


@mutation_context
@contextmanager
def scope(
    *,
    case_id,
    subject_id,
    provider,
    synthetic_fixtures_only=False,
    restricted_case_ids=None,
    **unused,
):
    enabled()
    if synthetic_fixtures_only is not True:
        raise cases.CaseConflict("synthetic_ack_required")
    with synthetic_queue_atomic():
        before = library.identity_snapshot(provider)
        # Scope discovery does not fetch source text. Capture the pure directory
        # generation before this identity callback; it cannot silently expand scope.
        initial = resolve_identity(provider, subject_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(546131,1)")
        identifiers = (
            set(Case.objects.filter(public_ref__in=initial.case_keys).values_list("pk", flat=True))
            if restricted_case_ids is None
            else {cases._uuid(value) for value in restricted_case_ids}
        )
        identifiers = dependency_case_ids(identifiers | {cases._uuid(case_id)})
        locked = {
            row.pk: row
            for row in Case.objects.filter(pk__in=identifiers).order_by("pk").select_for_update()
        }
        if len(locked) > 64:
            raise cases.CaseConflict("precise_citation_scope_bound")
        with ExitStack() as stack:
            guard = Guard(provider, subject_id, locked, stack, before)
            guard.owner_case_id = cases._uuid(case_id)
            row, _ = guard.actor(case_id)
            cases._verify(row)
            yield guard
            guard.callbacks()
        # Nested source readers can execute callbacks on exit; pure checks run last.
        guard.final_pins()
