"""Read local bytes, validate every stage, then emit one complete UTF-8 artifact."""

import ntpath
import sys
from pathlib import Path, PureWindowsPath

from apps.fast9_transcript_prepared_lineage.services import (
    MAX_RECEIPT_BYTES,
    build_lineage,
    load_pins,
    verify_receipt,
)
from apps.fatwa_drafts.intake import ValidationError
from tools.content_intake.cli import MAX_BYTES
from tools.transcript_pipeline.cli import SafeArgumentParser


def _read_local(value: str, limit: int = MAX_BYTES) -> tuple[bytes, str]:
    """FAST8 local-file boundary, extended only for bounded larger receipts.

    Like the upstream developer CLI, this is not a concurrent filesystem sandbox.
    Never read through a known symlink/junction, URL, UNC or device path.
    """
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
    for component in (*reversed(path.parents), path):
        if component.is_symlink() or component.is_junction():
            raise ValueError("local_regular_file_required")
    if not path.is_file():
        raise ValueError("local_regular_file_required")
    with path.open("rb") as source:
        return source.read(limit + 1), path.suffix.lower()


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        prog="python -B -m tools.fast9_transcript_prepared_lineage", allow_abbrev=False
    )
    parser.add_argument("input")
    parser.add_argument("--pins", required=True, help="Independently retained exact revision pins")
    parser.add_argument("--synthetic-fixtures-only", action="store_true")
    parser.add_argument(
        "--export", choices=("report", "prepared", "cues", "cue-csv"), default="report"
    )
    parser.add_argument(
        "--verify-receipt", help="Require exact replay of a retained receipt report"
    )
    args = parser.parse_args(argv)
    if not args.synthetic_fixtures_only:
        sys.stderr.buffer.write(b"SYNTHETIC_FIXTURES_REQUIRED\n")
        return 2
    try:
        raw, suffix = _read_local(args.input)
        pin_raw, _ = _read_local(args.pins)
        pins = load_pins(pin_raw)
        kwargs = dict(
            expected_input_sha256=pins["input_sha256"],
            expected_sources=pins["sources"],
            synthetic_fixtures_only=True,
        )
        if args.verify_receipt:
            receipt, _ = _read_local(args.verify_receipt, MAX_RECEIPT_BYTES)
            result = verify_receipt(receipt, raw, suffix, **kwargs)
        else:
            result = build_lineage(raw, suffix, **kwargs)
        output = {
            "report": result.json_bytes,
            "prepared": result.prepared_bytes,
            "cues": result.cue_json_bytes,
            "cue-csv": result.cue_csv_bytes,
        }[args.export]()
    except (OSError, ValueError, ValidationError):
        # Do not echo input text, local paths or parser snippets on failure.
        sys.stderr.buffer.write(b"TRANSCRIPT_LINEAGE_VALIDATION_FAILED\n")
        return 1
    sys.stdout.buffer.write(output)
    return 0
