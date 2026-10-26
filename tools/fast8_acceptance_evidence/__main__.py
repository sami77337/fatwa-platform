"""Deterministic UTF-8 JSON on stdout; no file paths, writes, or network options."""

import argparse
import sys

from apps.editorial_export.services import encode_json, require_development
from apps.fast8_acceptance_evidence.services import MAX_REPORT_BYTES, build_report, verify_report


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Never echo unknown arguments that might contain private paths or data.
        raise ValueError("invalid_arguments")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(
        description="Offline synthetic readiness only; NOT_DEPLOYED", allow_abbrev=False
    )
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--verify-stdin", action="store_true")
    try:
        args = parser.parse_args(argv)
        require_development(args.synthetic_fixtures_only)
        if args.verify_stdin:
            raw = sys.stdin.buffer.read(MAX_REPORT_BYTES + 1)
            verify_report(raw, synthetic_fixtures_only=True)
            output = encode_json(
                {
                    "schema": "fatwa.fast8-evidence-verification.v1",
                    "status": "PASS",
                    "scope": "EXACT_REPLAY_ONLY",
                    "acceptance": "BLOCKED",
                }
            )
            code = 0
        else:
            report = build_report(synthetic_fixtures_only=True)
            output = report.json_bytes
            code = 1 if report.payload()["producer"]["status"] != "PASS" else 0
    except (ValueError, OSError, ImportError):
        output = encode_json(
            {
                "schema": "fatwa.fast8-evidence-error.v1",
                "status": "FAIL",
                "reason": "invalid_invocation_or_verification_failed",
            }
        )
        code = 2
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
