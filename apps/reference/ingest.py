"""Atomic persistence of S1-validated records; no public HTTP write interface."""
import secrets
from collections.abc import Sequence
from dataclasses import dataclass

from django.db import connection, transaction

from .models import ReferenceEdition, ReferenceHeading, ReferenceWork
from .normalization import normalize_title
from .records import CatalogSpec, HeadingRecord, InvalidCatalog, PreparedCatalog, prepare_catalog


class CatalogConflict(InvalidCatalog):
    pass


@dataclass(frozen=True, slots=True)
class IngestResult:
    dry_run: bool
    unchanged: bool
    checksum: str
    heading_count: int
    edition_id: int | None


def _work_fields(spec: CatalogSpec) -> dict:
    return {"title_original": spec.work_title, "madhhab": spec.madhhab}


def _edition_fields(prepared: PreparedCatalog) -> dict:
    spec = prepared.spec
    return {
        "title": spec.edition_title, "publisher": spec.publisher,
        "source_archive_sha256": spec.source_archive_sha256,
        "source_input_sha256": spec.source_input_sha256, "input_name": spec.input_name,
        "ingest_checksum": prepared.checksum, "heading_count": spec.expected_rows,
        "root_count": spec.expected_roots, "max_depth": spec.expected_max_depth,
    }


def _assert_same(prepared: PreparedCatalog, edition: ReferenceEdition) -> None:
    if any(getattr(edition, key) != value for key, value in _edition_fields(prepared).items()):
        raise CatalogConflict("Changed source/edition: require a new reviewed edition key")
    existing = list(ReferenceHeading.objects.filter(edition=edition).order_by("source_order").values(
        "source_id", "source_row_id", "parent__source_row_id", "source_order", "position", "depth",
        "source_page_id", "source_part", "source_page_number", "source_entry_number",
        "title_original", "title_normalized",
    ))
    if len(existing) != len(prepared.records):
        raise CatalogConflict("Existing edition is incomplete; no silent repair")
    for stored, incoming in zip(existing, prepared.records, strict=True):
        expected = {
            "source_id": incoming.source_id, "source_row_id": incoming.source_row_id,
            "parent__source_row_id": incoming.parent_source_row_id,
            "source_order": incoming.source_order, "position": incoming.position,
            "depth": incoming.depth, "source_page_id": incoming.source_page_id,
            "source_part": incoming.source_part, "source_page_number": incoming.source_page_number,
            "source_entry_number": incoming.source_entry_number,
            "title_original": incoming.title_original,
            "title_normalized": normalize_title(incoming.title_original),
        }
        if stored != expected:
            raise CatalogConflict("Existing heading differs from validated input")


def ingest_catalog(
    spec: CatalogSpec, records: Sequence[HeadingRecord], *, dry_run: bool = True,
    expected_checksum: str | None = None,
) -> IngestResult:
    """Dry-run defaults to no writes. Commit requires the checksum returned by preview.

    S1 must verify the archive/member hashes and rights/scope before calling this
    development adapter. A checksum pins the exact mapped snapshot between calls.
    """
    prepared = prepare_catalog(spec, records)
    if not dry_run and (
        expected_checksum is None or not secrets.compare_digest(expected_checksum, prepared.checksum)
    ):
        raise CatalogConflict("Commit requires matching dry-run checksum")
    if connection.vendor != "postgresql":
        raise InvalidCatalog("The ORM ingest adapter requires PostgreSQL")
    work_key = {"source_namespace": spec.source_namespace, "source_book_id": spec.source_book_id}
    if dry_run:
        work = ReferenceWork.objects.filter(**work_key).first()
        edition = None
        if work is not None:
            if any(getattr(work, key) != value for key, value in _work_fields(spec).items()):
                raise CatalogConflict("Existing work identity has different metadata")
            edition = work.editions.filter(edition_key=spec.edition_key).first()
            if edition is not None:
                _assert_same(prepared, edition)
        return IngestResult(True, edition is not None, prepared.checksum, len(prepared.records),
                            edition.pk if edition else None)
    with transaction.atomic():
        work, _ = ReferenceWork.objects.get_or_create(**work_key, defaults=_work_fields(spec))
        # Serializes even competing edition imports for the same source work.
        work = ReferenceWork.objects.select_for_update().get(pk=work.pk)
        if any(getattr(work, key) != value for key, value in _work_fields(spec).items()):
            raise CatalogConflict("Existing work identity has different metadata")
        edition = work.editions.filter(edition_key=spec.edition_key).first()
        if edition is not None:
            _assert_same(prepared, edition)
            return IngestResult(False, True, prepared.checksum, len(prepared.records), edition.pk)
        edition = ReferenceEdition.objects.create(
            work=work, edition_key=spec.edition_key, **_edition_fields(prepared)
        )
        stored: dict[int, ReferenceHeading] = {}
        for depth in range(1, spec.expected_max_depth + 1):
            batch = []
            for row in prepared.records:
                if row.depth != depth:
                    continue
                batch.append(ReferenceHeading(
                    edition=edition, source_id=row.source_id, source_row_id=row.source_row_id,
                    parent=stored[row.parent_source_row_id] if row.parent_source_row_id else None,
                    source_order=row.source_order, position=row.position, depth=row.depth,
                    source_page_id=row.source_page_id, source_part=row.source_part,
                    source_page_number=row.source_page_number,
                    source_entry_number=row.source_entry_number, title_original=row.title_original,
                    title_normalized=normalize_title(row.title_original),
                ))
            # No ignore_conflicts: a constraint failure rolls back the entire snapshot.
            ReferenceHeading.objects.bulk_create(batch, batch_size=500)
            stored.update({heading.source_row_id: heading for heading in batch})
        _assert_same(prepared, edition)
        return IngestResult(False, False, prepared.checksum, len(prepared.records), edition.pk)
