"""Explicit, expiring server configuration for synthetic anonymous preview only."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

SHA = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True, slots=True)
class PublicationGrant:
    publication_id: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ReferenceGrant:
    edition_id: int
    source_row_id: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class PreviewPolicy:
    publications: tuple[PublicationGrant, ...]
    references: tuple[ReferenceGrant, ...]
    valid_until: datetime
    synthetic_fixtures_only: bool = False

    def validate(self) -> None:
        if (
            self.synthetic_fixtures_only is not True
            or type(self.publications) is not tuple
            or len(self.publications) > 64
            or type(self.references) is not tuple
            or len(self.references) > 768
            or not isinstance(self.valid_until, datetime)
            or not timezone.is_aware(self.valid_until)
            or not timezone.now() < self.valid_until <= timezone.now() + timedelta(hours=1)
        ):
            raise ValueError("invalid_preview_policy")
        ids, refs = set(), set()
        for grant in self.publications:
            if type(grant) is not PublicationGrant:
                raise ValueError("invalid_publication_grant")
            if (
                str(UUID(grant.publication_id)) != grant.publication_id
                or not SHA.fullmatch(grant.content_sha256)
                or grant.publication_id in ids
            ):
                raise ValueError("invalid_publication_grant")
            ids.add(grant.publication_id)
        for grant in self.references:
            if (
                type(grant) is not ReferenceGrant
                or type(grant.edition_id) is not int
                or type(grant.source_row_id) is not int
                or not 1 <= grant.edition_id <= 2**63 - 1
                or not 1 <= grant.source_row_id <= 2**63 - 1
                or not SHA.fullmatch(grant.source_sha256)
                or (grant.edition_id, grant.source_row_id) in refs
            ):
                raise ValueError("invalid_reference_grant")
            refs.add((grant.edition_id, grant.source_row_id))
