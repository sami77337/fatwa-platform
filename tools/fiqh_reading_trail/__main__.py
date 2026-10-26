"""Emit one deterministic synthetic navigation result to stdout; no file input."""

import argparse
import json
import sys
from dataclasses import asdict

from apps.reference.query import InvalidQuery, bounded_int


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo arbitrary input text or local paths from invalid options.
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid trail arguments; --synthetic-fixtures-only is required.\n")


def _row_id(value: str) -> int:
    try:
        return bounded_int(value, 1, 2**63 - 1)
    except InvalidQuery:
        raise argparse.ArgumentTypeError("Expected a positive source row ID") from None


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(
        description="Offline synthetic fiqh TOC trail; NOT_DEPLOYED", allow_abbrev=False
    )
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--source-row-id", type=_row_id, default=40)
    parser.add_argument(
        "--from-reference", action="store_true", help="Return to fixed intake-1 occurrence 1"
    )
    arguments = parser.parse_args(argv)

    from apps.fiqh_reading_trail.services import ReadingTrail
    from apps.reference_links.resolution import SnapshotCatalog
    from tools.fiqh_reading_trail.fixtures import (
        EDITION_ID,
        FIXTURE_ID,
        fixture_sha256,
        synthetic_case,
        synthetic_fixture,
    )

    try:
        prepared, headings = synthetic_fixture()
        trail = ReadingTrail(prepared, EDITION_ID)
        catalog = SnapshotCatalog(headings)
        if arguments.from_reference:
            result = trail.from_reference(
                synthetic_case(), 1, catalog, source_row_id=arguments.source_row_id
            )
        else:
            result = trail.navigate(arguments.source_row_id, catalog)
        report = {
            "schema": "fatwa.fiqh-reading-trail.v1",
            "synthetic_only": True,
            "fixture_id": FIXTURE_ID,
            "fixture_sha256": fixture_sha256(),
            "catalog_checksum": prepared.checksum,
            "source_pin_limit": "Fabricated fixture assertions; no owner archive inspected.",
            "gates": {
                "B": "NOT_PASSED",
                "C": "HOLD",
                "D": "HOLD",
                "E": "HOLD",
                "Phase01": "BLOCKED",
                "deployment": "NOT_DEPLOYED",
            },
            "trail": asdict(result),
        }
        output = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    except (ValueError, OSError):
        print("Synthetic trail could not be verified.", file=sys.stderr)
        return 1
    return 0 if result.status == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
