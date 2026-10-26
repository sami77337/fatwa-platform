"""Read a bounded local fixture; emit deterministic UTF-8 without persistence."""

import ntpath
import sys
from pathlib import Path, PureWindowsPath

from apps.fatwa_drafts.intake import ValidationError
from tools.content_intake.cli import MAX_BYTES
from tools.transcript_pipeline.cli import SafeArgumentParser


def _read_local(value: str) -> tuple[bytes, str]:
    windows = PureWindowsPath(value)
    if (
        value.startswith(("\\", "//"))
        or "://" in value
        or (windows.drive and not windows.root)
        or ntpath.isreserved(value)
        or ".." in windows.parts
    ):
        raise ValueError("local_regular_file_required")
    path = Path(value).absolute()
    # Check ancestors first: never traverse a known link/junction to another source.
    # This is a local developer CLI, not a filesystem sandbox against concurrent swaps.
    for component in (*reversed(path.parents), path):
        if component.is_symlink() or component.is_junction():
            raise ValueError("local_regular_file_required")
    if not path.is_file():
        raise ValueError("local_regular_file_required")
    with path.open("rb") as source:
        return source.read(MAX_BYTES + 1), path.suffix.lower()


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        prog="python -m tools.fast8_transcript_queue",
        description="Offline EPHEMERAL intake queue for fabricated manual transcript spans.",
        allow_abbrev=False,
    )
    parser.add_argument("input", help="Local UTF-8 CSV, JSON, or JSONL fabricated fixture")
    parser.add_argument(
        "--synthetic-fixtures-only",
        action="store_true",
        help="Attest every segment is fabricated and contains no private or real case data",
    )
    parser.add_argument("--export", choices=("report", "prepared"), default="report")
    args = parser.parse_args(argv)
    if not args.synthetic_fixtures_only:
        sys.stderr.buffer.write(b"SYNTHETIC_FIXTURES_REQUIRED\n")
        return 2
    try:
        raw, suffix = _read_local(args.input)
    except (OSError, ValueError):
        sys.stderr.buffer.write(b"LOCAL_FILE_READ_FAILED\n")
        return 1

    from apps.fast8_transcript_queue.services import build_transcript_queue

    try:
        queue = build_transcript_queue(raw, suffix, synthetic_fixtures_only=True)
        payload = queue.prepared_bytes() if args.export == "prepared" else queue.json_bytes()
    except ValidationError:
        sys.stderr.buffer.write(b"TRANSCRIPT_QUEUE_VALIDATION_FAILED\n")
        return 1
    sys.stdout.buffer.write(payload)
    return 0
