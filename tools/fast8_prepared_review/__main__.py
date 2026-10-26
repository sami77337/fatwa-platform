"""Run deterministic before/after diagnostics; no input/output file options."""

import argparse
import sys

from apps.editorial_export.services import ExportError, require_development
from apps.fast8_prepared_review.services import BridgeError, project, scenario
from apps.workflow_invariants.engine import canonical_bytes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--case", default="batch-synthetic-csv-1")
    args = parser.parse_args(argv)
    try:
        require_development(args.synthetic_fixtures_only)
        result = project(scenario(args.case, synthetic_fixtures_only=True))
    except (BridgeError, ExportError) as exc:
        parser.error(str(exc))
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
