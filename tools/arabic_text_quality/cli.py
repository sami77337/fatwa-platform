"""Read bounded local UTF-8 fixtures without rewriting bytes or line endings."""

import argparse
import ntpath
import os
import stat
import sys
from pathlib import Path, PureWindowsPath
from typing import NoReturn

from apps.arabic_text_quality.service import MAX_TEXT_LENGTH, compare_texts, inspect_text

MAX_INPUT_BYTES = MAX_TEXT_LENGTH * 4
_SEVERITIES = {"info": 0, "warning": 1, "error": 2}


class SafeArgumentParser(argparse.ArgumentParser):
    """Never echo submitted source, filenames, or unknown arguments in errors."""

    def error(self, message: str) -> NoReturn:
        self.exit(2, "ARGUMENTS_INVALID\n")


def _read_local_text(filename: str) -> str:
    windows_path = PureWindowsPath(filename)
    if (
        filename.startswith(("\\", "//"))
        or (windows_path.drive and not windows_path.root)
        or ntpath.isreserved(filename)
    ):
        raise ValueError("local_file_required")
    path = Path(filename).absolute()
    # Refuse network paths and redirected paths before opening any input stream.
    if str(path).startswith(("\\", "//")):
        raise ValueError("local_file_required")
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise ValueError("local_regular_file_required")
    if not path.is_file():
        raise ValueError("local_regular_file_required")
    with path.open("rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_INPUT_BYTES:
            raise ValueError("bounded_regular_file_required")
        raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input_too_large")
    # utf-8 (not utf-8-sig) deliberately retains a BOM as U+FEFF for inspection.
    return raw.decode("utf-8", errors="strict")


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        prog="python -m tools.arabic_text_quality",
        description="Offline Arabic text quality inspection; synthetic data only; no source writes.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--synthetic-only", action="store_true", help="Attest all text is fabricated"
    )
    parser.add_argument("--input", required=True, help="Local UTF-8 question or revised text")
    parser.add_argument("--before", help="Optional local UTF-8 original text for comparison")
    parser.add_argument("--kind", choices=("question", "revision"), default="question")
    parser.add_argument(
        "--fail-on", choices=tuple(_SEVERITIES), help="Exit 1 on this severity or higher"
    )
    args = parser.parse_args(argv)
    if not args.synthetic_only:
        print("SYNTHETIC_ONLY_REQUIRED", file=sys.stderr)
        return 2
    try:
        text = _read_local_text(args.input)
        if args.before is None:
            report = inspect_text(text, synthetic_only=True, kind=args.kind)
        else:
            before = _read_local_text(args.before)
            report = compare_texts(before, text, synthetic_only=True, kind=args.kind)
    except (OSError, ValueError, TypeError):
        print("INPUT_INVALID", file=sys.stderr)
        return 2
    # ASCII escapes prevent terminal control/bidi execution and survive Windows encodings.
    sys.stdout.buffer.write((report.to_json() + "\n").encode("ascii"))
    if args.fail_on is not None and any(
        _SEVERITIES[item.severity] >= _SEVERITIES[args.fail_on] for item in report.diagnostics
    ):
        return 1
    return 0
