"""Print the deterministic synthetic integration journey as UTF-8 JSON."""

import argparse
import sys


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # Argument values may contain private paths or text. Never echo them.
        self.print_usage(sys.stderr)
        self.exit(2, "Journey arguments invalid; --synthetic-fixtures-only is required.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(
        description="Read-only fixed synthetic journey; NOT_DEPLOYED",
        allow_abbrev=False,
    )
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    arguments = parser.parse_args(argv)

    from apps.fast6_journey.services import JourneyError, run_journey

    try:
        report = run_journey(synthetic_fixtures_only=arguments.synthetic_fixtures_only)
        sys.stdout.buffer.write(report.json_bytes)
        sys.stdout.buffer.flush()
    except (JourneyError, ValueError, OSError):
        print("Journey failed: synthetic development guard or verification error.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
