"""Lane-owned fabricated contract; hashes identify these bytes, not owner sources."""

import hashlib
import json
from dataclasses import asdict

from apps.reference.records import CatalogSpec, HeadingRecord, prepare_catalog

FIXTURE_ID = "fast9-reference-consistency-synthetic-v1"


def fixture_bytes() -> bytes:
    return json.dumps(
        [
            asdict(
                HeadingRecord(
                    "synthetic-root",
                    10,
                    None,
                    5,
                    2,
                    1,
                    101,
                    "تمهيد",
                    7,
                    "  كِتَابٌ اصطناعي e\u0301\r\n  ",
                )
            ),
            asdict(
                HeadingRecord(
                    "synthetic-child", 30, 10, 15, 3, 2, 102, "الأول", 3, "بابٌ اصطناعي", 2
                )
            ),
            asdict(
                HeadingRecord(
                    "synthetic-sibling", 20, 10, 25, 8, 2, 103, "الثاني", 12, "بابٌ اصطناعي"
                )
            ),
            asdict(
                HeadingRecord(
                    "synthetic-other-root", 50, None, 35, 6, 1, 104, "الثالث", 1, "خاتمة اصطناعية"
                )
            ),
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fixture_sha256() -> str:
    return hashlib.sha256(fixture_bytes()).hexdigest()


def synthetic_fixture():
    spec = CatalogSpec(
        source_namespace="fast9-synthetic",
        source_book_id="invented-reference",
        work_title="مرجع اصطناعي لاختبار الاتساق",
        madhhab="اصطناعي",
        edition_key=FIXTURE_ID,
        edition_title="طبعة اصطناعية",
        publisher="ناشر اصطناعي",
        source_archive_sha256=hashlib.sha256(b"synthetic-no-owner-archive").hexdigest(),
        source_input_sha256=fixture_sha256(),
        input_name=FIXTURE_ID + ".json",
        expected_rows=4,
        expected_roots=2,
        expected_max_depth=2,
    )
    return prepare_catalog(spec, tuple(HeadingRecord(**row) for row in json.loads(fixture_bytes())))
