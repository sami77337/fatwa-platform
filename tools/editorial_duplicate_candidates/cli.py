"""Emit a deterministic UTF-8 report using only the built-in synthetic catalog."""

import argparse
import sys


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Do not echo untrusted argument values, paths or accidentally supplied data.
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid arguments; --synthetic-fixtures-only is required.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(
        prog="python -m tools.editorial_duplicate_candidates",
        description="Offline synthetic duplicate candidates; NOT_DEPLOYED / GATES_HOLD.",
        allow_abbrev=False,
    )
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    arguments = parser.parse_args(argv)

    from apps.editorial_duplicate_candidates.services import (
        DuplicateCandidateError,
        build_duplicate_report,
    )
    from apps.editorial_workbench.services import WorkbenchDataError

    try:
        report = build_duplicate_report(synthetic_fixtures_only=arguments.synthetic_fixtures_only)
        payload = report.json_bytes()
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
        else:
            sys.stdout.write(payload.decode("utf-8"))
    except (DuplicateCandidateError, WorkbenchDataError, OSError):
        print(
            "Duplicate candidate report failed: synthetic source validation error.", file=sys.stderr
        )
        return 1
    return 0
