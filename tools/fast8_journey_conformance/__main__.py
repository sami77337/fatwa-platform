"""Bounded stdin contracts; fixed synthetic sources; UTF-8 report on stdout."""

import argparse
import sys


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Conformance arguments invalid; explicit synthetic opt-in required.\n")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(allow_abbrev=False)
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--scenario")
    parser.add_argument("--contract-stdin", action="store_true")
    args = parser.parse_args(argv)
    from apps.fast8_journey_conformance.services import MAX_CONTRACT_BYTES, run_conformance

    try:
        contract = sys.stdin.buffer.read(MAX_CONTRACT_BYTES + 1) if args.contract_stdin else None
        report = run_conformance(
            contract, scenario=args.scenario, synthetic_fixtures_only=args.synthetic_fixtures_only
        )
        sys.stdout.buffer.write(report.json_bytes)
        sys.stdout.buffer.flush()
        return 3 if report.payload()["result"] == "NOT_CONNECTED" else 0
    except (ValueError, OSError, KeyError, TypeError):
        # No caller-controlled data, file paths or service exception text in diagnostics.
        print("Conformance failed: invalid, missing or stale synthetic evidence.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
