"""Bounded local files in, deterministic UTF-8 bytes out; no media or source writes."""

import argparse
import ntpath
import os
import stat
import sys
from pathlib import Path, PureWindowsPath

from apps.fast8_segment_timeline.service import ValidationError, diagnose_file
from apps.transcript_pipeline import MAX_BYTES
from tools.content_intake.cli import parse_json


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "ARGUMENTS_INVALID\n")


def _read_local(filename: str) -> bytes:
    windows = PureWindowsPath(filename)
    if (
        filename.startswith(("\\", "//"))
        or (windows.drive and not windows.root)
        or ntpath.isreserved(filename)
    ):
        raise ValidationError("input: local_file_required")
    path = Path(filename).absolute()
    if (
        str(path).startswith(("\\", "//"))
        or any(part.is_symlink() or part.is_junction() for part in (path, *path.parents))
        or not path.is_file()
    ):
        raise ValidationError("input: local_regular_file_required")
    with path.open("rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
            raise ValidationError("input: bounded_regular_file_required")
        raw = stream.read(MAX_BYTES + 1)
    if not 1 <= len(raw) <= MAX_BYTES:
        raise ValidationError("input: invalid_size")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        prog="python -m tools.fast8_segment_timeline",
        allow_abbrev=False,
        description="Offline synthetic manual timeline diagnostics; no media operations.",
    )
    parser.add_argument("input", help="Local fabricated transcript CSV/JSON/JSONL")
    parser.add_argument("--synthetic-fixtures-only", action="store_true")
    parser.add_argument("--export", choices=("report", "cues-json", "cues-csv"), default="report")
    parser.add_argument(
        "--durations", help="Local JSON object mapping exact source IDs to integer ms"
    )
    args = parser.parse_args(argv)
    if not args.synthetic_fixtures_only:
        sys.stderr.buffer.write(b"SYNTHETIC_FIXTURES_REQUIRED\n")
        return 2
    try:
        raw = _read_local(args.input)
        durations = None
        if args.durations:
            durations = parse_json(_read_local(args.durations).decode("utf-8-sig"))
            if not isinstance(durations, dict):
                raise ValidationError("durations: object_required")
        report = diagnose_file(
            raw,
            Path(args.input).suffix,
            synthetic_fixtures_only=True,
            source_durations_ms=durations,
        )
        if args.export == "cues-json":
            payload = report.cue_json_bytes()
        elif args.export == "cues-csv":
            payload = report.cue_csv_bytes()
        else:
            payload = report.json_bytes()
    except (OSError, ValueError, RecursionError):
        sys.stderr.buffer.write(b"TIMELINE_INPUT_OR_EXPORT_INVALID\n")
        return 1
    sys.stdout.buffer.write(payload)
    return 0 if parse_json(report.json_bytes())["cues_allowed"] else 1
