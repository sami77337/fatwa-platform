"""Exercise the integration contract using an explicit independent synthetic reader."""

import argparse
import json
from contextlib import contextmanager
from dataclasses import asdict

from apps.fast8_fiqh_navigation.services import CatalogNavigation, CatalogSnapshot
from apps.reference_links.resolution import SnapshotCatalog
from tools.fiqh_reading_trail.fixtures import (
    EDITION_ID,
    FIXTURE_ID,
    fixture_sha256,
    synthetic_case,
    synthetic_fixture,
)


class SyntheticReader:
    @contextmanager
    def snapshot(self, edition_id):
        prepared, headings = synthetic_fixture()
        yield CatalogSnapshot(EDITION_ID, prepared, SnapshotCatalog(headings))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--source-row-id", default="40")
    parser.add_argument("--from-reference", action="store_true")
    args = parser.parse_args(argv)
    adapter = CatalogNavigation(synthetic_fixture()[0], EDITION_ID)
    query = {"edition": str(EDITION_ID), "source_row_id": args.source_row_id}
    result = (
        adapter.from_reference(query, synthetic_case(), 1, SyntheticReader())
        if args.from_reference
        else adapter.navigate(query, SyntheticReader())
    )
    print(
        json.dumps(
            {
                "fixture_id": FIXTURE_ID,
                "fixture_sha256": fixture_sha256(),
                "synthetic_only": True,
                "database_catalog": "NOT_RUN",
                "owner_archive": "NOT_SUPPLIED",
                "source_acceptance": "NOT_RUN",
                "deployment": "NOT_DEPLOYED",
                "result": asdict(result),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0 if result.trail.status == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
