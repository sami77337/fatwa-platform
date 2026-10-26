"""Join pinned topology to independent catalog evidence without discovering editions."""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from django.core.exceptions import AppRegistryNotReady, ImproperlyConfigured

from apps.fiqh_reading_trail.services import ReadingTrail, TrailResult
from apps.reference.query import MAX_SOURCE_ID, InvalidQuery, bounded_int
from apps.reference.records import PreparedCatalog
from apps.reference_links.resolution import CatalogReadError, ReadOnlyCatalog
from apps.reference_triage.services import CaseTriage


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    edition_id: int
    prepared: PreparedCatalog
    evidence: ReadOnlyCatalog


class CatalogReader(Protocol):
    def snapshot(self, edition_id: int) -> AbstractContextManager[CatalogSnapshot]: ...


@dataclass(frozen=True, slots=True)
class NavigationResult:
    trail: TrailResult
    edition_title: str | None = None
    publisher: str | None = None


def closed(reason: str) -> NavigationResult:
    return NavigationResult(TrailResult("unverified", reason))


class CatalogNavigation:
    """Explicit trusted source contract, plus freshly checked catalog on every call.

    The contract must come from the caller, never reconstructed from the database
    being checked. Construction does no I/O. No reader means NOT_CONNECTED.
    """

    def __init__(self, prepared: PreparedCatalog, edition_id: int) -> None:
        self._trail = ReadingTrail(prepared, edition_id)

    def navigate(
        self,
        query: Mapping[str, str],
        reader: CatalogReader | None = None,
    ) -> NavigationResult:
        return self._navigate(query, reader)

    def from_reference(
        self,
        query: Mapping[str, str],
        case: CaseTriage,
        reference_ordinal: int,
        reader: CatalogReader | None = None,
    ) -> NavigationResult:
        """Retain the existing research bridge's occurrence recheck and return link."""
        return self._navigate(query, reader, case, reference_ordinal, from_reference=True)

    def _navigate(
        self,
        query: Mapping[str, str],
        reader: CatalogReader | None,
        case: CaseTriage | None = None,
        reference_ordinal: int | None = None,
        *,
        from_reference: bool = False,
    ) -> NavigationResult:
        try:
            if not isinstance(query, Mapping) or set(query) != {"edition", "source_row_id"}:
                raise InvalidQuery("Explicit edition and heading required")
            # QueryDict duplicates must not silently pick the last identity.
            if callable(getattr(query, "getlist", None)) and any(
                len(query.getlist(key)) != 1 for key in query
            ):
                raise InvalidQuery("Repeated identity")
            if any(type(query[key]) is not str for key in query):
                raise InvalidQuery("Query strings required")
            edition = bounded_int(query["edition"], 1, MAX_SOURCE_ID)
            row = bounded_int(query["source_row_id"], 1, MAX_SOURCE_ID)
        except (InvalidQuery, TypeError, KeyError):
            return closed("exact_identity_required")
        if edition != self._trail.edition_id:
            return closed("edition_mismatch")
        if reader is None:
            return closed("NOT_CONNECTED")
        try:
            with reader.snapshot(edition) as snapshot:
                if type(snapshot) is not CatalogSnapshot or type(snapshot.edition_id) is not int:
                    return closed("catalog_evidence_mismatch")
                # Revalidate independent topology; Python equality alone accepts bool/int aliases.
                live = ReadingTrail(snapshot.prepared, snapshot.edition_id)
                if live.edition_id != edition or live.prepared != self._trail.prepared:
                    return closed("catalog_evidence_mismatch")
                if not from_reference:
                    result = self._trail.navigate(row, snapshot.evidence)
                else:
                    result = self._trail.from_reference(
                        case, reference_ordinal, snapshot.evidence, source_row_id=row
                    )
                if result.status != "verified":
                    return NavigationResult(result)
                return NavigationResult(
                    result, live.prepared.spec.edition_title, live.prepared.spec.publisher
                )
        except (CatalogReadError, AppRegistryNotReady, ImproperlyConfigured):
            return closed("catalog_unavailable")
        except (ValueError, TypeError, AttributeError):
            return closed("catalog_evidence_mismatch")
