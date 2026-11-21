"""Explicit public FT disclosure and exact lookup; private case IDs stay private.

The reference mapping is current server authority, never a durable access grant.
Only its explicitly listed approved publication can be looked up. No global case
search, approximate fallback or anonymous staff identity is created.
"""

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication.models import PublicationEdition
from apps.platform_recovery.integration import mutation_context
from apps.public_answer_media.boundaries import _epoch, identity_pin
from apps.public_answer_media.public import publication_projection

from . import services as preview

REFERENCE = re.compile(r"FT-[0-9]{4}-[A-F0-9]{20}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True, slots=True)
class FatwaReferenceGrant:
    reference: str
    publication_id: str
    content_sha256: str
    provider_id: str
    subject_id: str
    auth_epoch: str


@dataclass(frozen=True, slots=True)
class PublicFatwaReferences:
    grants: tuple[FatwaReferenceGrant, ...]
    valid_until: datetime
    synthetic_fixtures_only: bool = False

    def validate(self):
        now = timezone.now()
        if (
            self.synthetic_fixtures_only is not True
            or type(self.grants) is not tuple
            or len(self.grants) > 64
            or not isinstance(self.valid_until, datetime)
            or timezone.is_naive(self.valid_until)
            or not now < self.valid_until <= now + timedelta(hours=1)
        ):
            raise preview.PreviewUnavailable()
        references, editions = set(), set()
        for grant in self.grants:
            if type(grant) is not FatwaReferenceGrant:
                raise preview.PreviewUnavailable()
            if any(
                type(value) is not str or not 1 <= len(value) <= 128
                for value in (
                    grant.reference,
                    grant.publication_id,
                    grant.content_sha256,
                    grant.provider_id,
                    grant.subject_id,
                    grant.auth_epoch,
                )
            ):
                raise preview.PreviewUnavailable()
            try:
                identifier = str(UUID(grant.publication_id))
            except ValueError:
                raise preview.PreviewUnavailable() from None
            if (
                not REFERENCE.fullmatch(grant.reference)
                or not SHA.fullmatch(grant.content_sha256)
                or identifier != grant.publication_id
                or grant.reference in references
                or grant.publication_id in editions
            ):
                raise preview.PreviewUnavailable()
            references.add(grant.reference)
            editions.add(grant.publication_id)


def enabled():
    return (
        os.environ.get("FATWA_PRODUCTION") == "0"
        and getattr(settings, "FATWA_REFERENCE_LOOKUP_ENABLED", False) is True
    )


def policy():
    selected = getattr(settings, "FATWA_PUBLIC_FATWA_REFERENCES", None)
    if not enabled() or type(selected) is not PublicFatwaReferences:
        raise preview.PreviewUnavailable()
    selected.validate()
    return selected


def optional_grant(publication_id):
    if not enabled() or getattr(settings, "FATWA_PUBLIC_FATWA_REFERENCES", None) is None:
        return None
    return next((g for g in policy().grants if g.publication_id == str(publication_id)), None)


@mutation_context
@contextmanager
def projection(*, reference=None, publication_id=None):
    if (reference is None) == (publication_id is None):
        raise preview.PreviewUnavailable()
    selected = policy()
    if reference is not None and (type(reference) is not str or not REFERENCE.fullmatch(reference)):
        raise preview.PreviewUnavailable()
    grant = next(
        (
            item
            for item in selected.grants
            if (
                item.reference == reference
                if reference is not None
                else item.publication_id == str(publication_id)
            )
        ),
        None,
    )
    if grant is None:
        raise preview.PreviewUnavailable()
    directory = getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)
    if directory is None or getattr(directory, "provider_id", None) != grant.provider_id:
        raise preview.PreviewUnavailable()
    try:
        epoch = _epoch(directory, "projection_epoch")
        with publication_projection(grant.publication_id, include_media=False) as result:
            source = PublicationEdition.objects.get(pk=grant.publication_id)
            case = Case.objects.get(pk=source.case_id)
            approved = source.actions.get(action="APPROVE")
            if (
                source.content_sha256 != grant.content_sha256
                or case.public_ref != grant.reference
                or (approved.provider_id, approved.subject_id, approved.auth_epoch)
                != (grant.provider_id, grant.subject_id, grant.auth_epoch)
            ):
                raise preview.PreviewUnavailable()
            actor = cases._identity(directory, grant.subject_id, case)
            if actor.auth_epoch != grant.auth_epoch:
                raise preview.PreviewUnavailable()
            actor_pin = (*identity_pin(actor), actor.valid_until)
            deadline = actor.valid_until

            def check():
                if (
                    not enabled()
                    or getattr(settings, "FATWA_PUBLIC_FATWA_REFERENCES", None) is not selected
                    or getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None) is not directory
                    or _epoch(directory, "projection_epoch") != epoch
                ):
                    raise preview.PreviewUnavailable()
                selected.validate()
                if timezone.now() >= deadline:
                    raise preview.PreviewUnavailable()

            check()
            edition = {
                **result["publication"],
                "history": preview._history(preview.policy(), source),
            }
            yield {"edition": edition, "fatwa_reference": grant.reference}
            current = cases._identity(directory, grant.subject_id, case)
            if (*identity_pin(current), current.valid_until) != actor_pin:
                raise preview.PreviewUnavailable()
            check()
        # Source readers may invoke callbacks during exit. Only pure snapshots
        # and current deadlines may follow before returning the rendered bytes.
        check()
    except cases.CaseConflict as exc:
        raise preview.PreviewUnavailable() from exc
