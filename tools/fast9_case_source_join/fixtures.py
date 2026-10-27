"""Fabricated coherent catalog for the existing Wave7 original occurrences.

Opaque IDs are the existing wave7-title-* identities, never a translation of
the unrelated fast7c reading-trail fixture. a/b are synthetic assertion pins,
not owner-archive digests. No source archive is opened or reconstructed.
"""

import json
from dataclasses import asdict
from hashlib import sha256

from apps.reference.records import CatalogSpec, HeadingRecord, prepare_catalog
from apps.reference_links.resolution import Heading

EDITION_ID = 7001
FIXTURE_ID = "fast9-case-source-join-synthetic-v1"
TITLES = ("كِتَابٌ اصطناعي", "بابٌ اصطناعي أول", "بابٌ اصطناعي ثان")


def synthetic_fixture():
    spec = CatalogSpec(
        "wave7-synthetic-toc",
        "622",
        "مرجع اصطناعي لتجارب Wave7",
        "اصطناعي فقط",
        "wave7-synthetic-edition-v1",
        "طبعة اصطناعية",
        "ناشر اصطناعي",
        "a" * 64,
        "b" * 64,
        "fast9-case-source-join-synthetic.json",
        3,
        1,
        2,
    )
    records = tuple(
        HeadingRecord(
            f"wave7-title-{row}",
            row,
            None if row == 1 else 1,
            row,
            1 if row == 1 else row - 1,
            1 if row == 1 else 2,
            row,
            "الأول",
            6 + row,
            title,
        )
        for row, title in enumerate(TITLES, 1)
    )
    headings = tuple(
        Heading(
            EDITION_ID,
            row,
            spec.work_title,
            title,
            "الأول",
            6 + row,
            (title,) if row == 1 else (TITLES[0], title),
            spec.source_namespace,
            spec.source_book_id,
            spec.source_input_sha256,
            spec.edition_key,
            spec.source_archive_sha256,
        )
        for row, title in enumerate(TITLES, 1)
    )
    return prepare_catalog(spec, records), headings


def fixture_sha256():
    prepared, headings = synthetic_fixture()
    raw = json.dumps(
        {
            "fixture_id": FIXTURE_ID,
            "edition_id": EDITION_ID,
            "prepared": asdict(prepared),
            "headings": [asdict(h) for h in headings],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(raw).hexdigest()
