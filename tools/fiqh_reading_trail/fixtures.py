"""Invented topology; a/b pins are assertions, never hashes of owner archives."""

import hashlib
import json
from dataclasses import asdict

from apps.reference.records import CatalogSpec, HeadingRecord, prepare_catalog
from apps.reference_links.resolution import Heading, SnapshotCatalog
from apps.reference_triage.services import build_investigation

EDITION_ID = 7001
FIXTURE_ID = "fast7c-reading-trail-synthetic-v1"
ROOT = "كِتَابٌ اصطناعي"
CHILD = "بابٌ اصطناعي أول"
DETAIL = "  فَصْلٌ <اصطناعي> e\u0301  "
OTHER_ROOT = "كتاب ثانٍ اصطناعي"

# Deliberately non-contiguous IDs, source orders and positions. The printed page
# decreases at row 40, so neither pages nor numeric row IDs define traversal.
ROWS = (
    (1, None, 10, 2, 1, "الأول", 7, ROOT, (ROOT,)),
    (2, 1, 20, 3, 2, "الأول", 8, CHILD, (ROOT, CHILD)),
    (40, 2, 30, 4, 3, "تمهيد", 3, DETAIL, (ROOT, CHILD, DETAIL)),
    (41, 40, 40, 1, 4, "الثاني", 11, "فرع اصطناعي", (ROOT, CHILD, DETAIL, "فرع اصطناعي")),
    (
        42,
        41,
        50,
        1,
        5,
        "الثاني",
        12,
        "مسألة فهرسية",
        (ROOT, CHILD, DETAIL, "فرع اصطناعي", "مسألة فهرسية"),
    ),
    (3, 1, 60, 8, 2, "الأول", 9, "بابٌ اصطناعي ثان", (ROOT, "بابٌ اصطناعي ثان")),
    (8, None, 70, 7, 1, "الثالث", 20, OTHER_ROOT, (OTHER_ROOT,)),
    (9, 8, 80, 5, 2, "الثالث", 21, CHILD, (OTHER_ROOT, CHILD)),
    (10, 8, 90, 9, 2, "الثالث", 21, "خاتمة اصطناعية", (OTHER_ROOT, "خاتمة اصطناعية")),
)


def synthetic_fixture():
    """Return authoritative contracts and an independent explicit catalog snapshot."""
    spec = CatalogSpec(
        source_namespace="wave7-synthetic-toc",
        source_book_id="622",
        work_title="مرجع اصطناعي لتجارب Wave7",
        madhhab="اصطناعي",
        edition_key="wave7-synthetic-edition-v1",
        edition_title="طبعة اصطناعية",
        publisher="ناشر اصطناعي",
        source_archive_sha256="a" * 64,
        source_input_sha256="b" * 64,
        input_name="fast7c-synthetic.json",
        expected_rows=len(ROWS),
        expected_roots=2,
        expected_max_depth=5,
    )
    records = tuple(
        HeadingRecord(
            f"synthetic-{ident}",
            ident,
            parent,
            order,
            position,
            depth,
            100 + ident,
            part,
            page,
            title,
        )
        for ident, parent, order, position, depth, part, page, title, _ in ROWS
    )
    headings = tuple(
        Heading(
            EDITION_ID,
            ident,
            spec.work_title,
            title,
            part,
            page,
            path,
            spec.source_namespace,
            spec.source_book_id,
            spec.source_input_sha256,
            spec.edition_key,
            spec.source_archive_sha256,
        )
        for ident, _, _, _, _, part, page, title, path in ROWS
    )
    return prepare_catalog(spec, records), headings


def fixture_bytes() -> bytes:
    prepared, headings = synthetic_fixture()
    return json.dumps(
        {
            "fixture_id": FIXTURE_ID,
            "edition_id": EDITION_ID,
            "prepared": asdict(prepared),
            "catalog": [asdict(row) for row in headings],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def fixture_sha256() -> str:
    return hashlib.sha256(fixture_bytes()).hexdigest()


def synthetic_case():
    """Use the existing fixed verified occurrence; never fabricate its status."""
    return next(case for case in build_investigation().cases if case.case.key == "intake-1")


def synthetic_catalog():
    return SnapshotCatalog(synthetic_fixture()[1])
