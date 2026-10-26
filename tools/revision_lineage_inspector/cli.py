"""Read-only synthetic CLI. Only fixed fixtures are accepted; JSON goes to stdout."""

import argparse
import json
import sys
from hashlib import sha256

from apps.revision_lineage_inspector import LineageInputError, inspect_lineage

from .fixtures import FIXTURE_ID, SCENARIOS, synthetic_fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect immutable synthetic revision lineage")
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="consistent")
    args = parser.parse_args(argv)
    fixture = synthetic_fixture(args.scenario)
    try:
        report = inspect_lineage(
            fixture.record,
            expected_case_id=fixture.expected_case_id,
            workflow=fixture.workflow,
            expected_row_id=fixture.expected_row_id,
            expected_batch_id=fixture.expected_batch_id,
            source_payload=fixture.source_payload,
            synthetic_fixtures_only=args.synthetic_fixtures_only,
        ).to_dict()
        output = {
            "fixture_id": FIXTURE_ID,
            "scenario": args.scenario,
            "source_payload_sha256": sha256(fixture.source_payload).hexdigest(),
            "report": report,
        }
        sys.stdout.buffer.write(
            json.dumps(
                output, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
            + b"\n"
        )
        return 1 if report["status"] == "INCONSISTENT" else 0
    except LineageInputError:
        sys.stderr.buffer.write(b'{"status":"INVALID_INPUT","reason":"lineage_input_invalid"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
