"""Read one bounded local fixture and emit an all-or-nothing UTF-8 export."""

import argparse
import ntpath
import sys
from pathlib import Path, PureWindowsPath

from apps.transcript_pipeline import MAX_BYTES, ValidationError, segment_file


class SafeArgumentParser(argparse.ArgumentParser):
    """Do not echo unknown arguments, paths, or submitted values in diagnostics."""

    def error(self, message: str) -> None:
        sys.stderr.buffer.write(b"ARGUMENTS_INVALID\n")
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        prog="python -m tools.transcript_pipeline",
        description="Offline synthetic fixtures only; manually supplied segment boundaries.",
        allow_abbrev=False,
    )
    parser.add_argument("input", help="Local UTF-8 CSV, JSON, or JSONL fixture")
    parser.add_argument(
        "--synthetic-fixtures-only",
        action="store_true",
        help="Attest that every supplied segment is fabricated and contains no private records",
    )
    parser.add_argument("--export", choices=("report", "prepared"), default="report")
    args = parser.parse_args(argv)
    if not args.synthetic_fixtures_only:
        sys.stderr.buffer.write(b"SYNTHETIC_FIXTURES_REQUIRED\n")
        return 2
    windows_path = PureWindowsPath(args.input)
    if (
        args.input.startswith(("\\", "//"))
        or (windows_path.drive and not windows_path.root)
        or ntpath.isreserved(args.input)
    ):
        sys.stderr.buffer.write(b"LOCAL_FILE_READ_FAILED\n")
        return 1
    path = Path(args.input)
    try:
        if path.is_symlink() or path.is_junction() or not path.is_file():
            sys.stderr.buffer.write(b"LOCAL_FILE_READ_FAILED\n")
            return 1
        with path.open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        sys.stderr.buffer.write(b"LOCAL_FILE_READ_FAILED\n")
        return 1
    try:
        batch = segment_file(
            raw,
            path.suffix.lower(),
            synthetic_fixtures_only=True,
        )
        payload = batch.prepared_bytes() if args.export == "prepared" else batch.json_bytes()
    except ValidationError:
        sys.stderr.buffer.write(b"TRANSCRIPT_VALIDATION_FAILED\n")
        return 1
    sys.stdout.buffer.write(payload)
    return 0
