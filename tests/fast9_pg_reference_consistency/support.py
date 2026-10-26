"""Independent expected ORM projection for offline tests only."""

from dataclasses import asdict

from apps.fast9_pg_reference_consistency.services import CatalogRows
from apps.reference.normalization import normalize_title
from tools.fast9_pg_reference_consistency.fixtures import synthetic_fixture

EDITION_ID = 7009


def snapshot():
    pin = synthetic_fixture()
    spec = pin.spec
    work = {
        "id": 99,
        "source_namespace": spec.source_namespace,
        "source_book_id": spec.source_book_id,
        "title_original": spec.work_title,
        "madhhab": spec.madhhab,
    }
    edition = {
        "id": EDITION_ID,
        "work_id": 99,
        "edition_key": spec.edition_key,
        "title": spec.edition_title,
        "publisher": spec.publisher,
        "source_archive_sha256": spec.source_archive_sha256,
        "source_input_sha256": spec.source_input_sha256,
        "input_name": spec.input_name,
        "ingest_checksum": pin.checksum,
        "heading_count": 4,
        "root_count": 2,
        "max_depth": 2,
    }
    rows = []
    for record in pin.records:
        row = asdict(record)
        parent = row.pop("parent_source_row_id")
        row.update(
            id=1000 + record.source_row_id,
            edition_id=EDITION_ID,
            parent_id=1000 + parent if parent else None,
            parent__source_row_id=parent,
            parent__edition_id=EDITION_ID if parent else None,
            title_normalized=normalize_title(record.title_original),
        )
        rows.append(row)
    return CatalogRows((work,), (edition,), tuple(rows))
