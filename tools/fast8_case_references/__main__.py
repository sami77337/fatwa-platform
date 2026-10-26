"""Print a deterministic UTF-8 technical dossier for one synthetic case."""

import argparse
import sys

from apps.editorial_workbench.packets import serialize_packet
from apps.fast8_case_references.services import build_dossier
from apps.fiqh_reading_trail.services import ReadingTrail
from apps.reference_links.resolution import SnapshotCatalog
from tools.fiqh_reading_trail.fixtures import (
    EDITION_ID,
    FIXTURE_ID,
    fixture_sha256,
    synthetic_fixture,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid dossier arguments; use --help.\n")


def main(argv=None):
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--case", required=True)
    args = parser.parse_args(argv)
    try:
        prepared, headings = synthetic_fixture()
        dossier = build_dossier(
            args.case,
            synthetic_fixtures_only=True,
            trail=ReadingTrail(prepared, EDITION_ID),
            catalog=SnapshotCatalog(headings),
        )
        payload = dossier.payload()
        payload["fixture"] = {
            "id": FIXTURE_ID,
            "sha256": fixture_sha256(),
            "source_pins": "fabricated assertions; no owner archive inspected",
        }
        sys.stdout.buffer.write(serialize_packet(payload))
        sys.stdout.buffer.flush()
    except (ValueError, OSError):
        print("Synthetic dossier could not be verified.", file=sys.stderr)
        return 1
    return 0 if payload["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
