"""Emit a preview to stdout without reading or writing user-selected files."""

import argparse
import sys

from apps.fast8_intake_recovery.services import BATCH_IDS, preview_recovery
from apps.fatwa_drafts.intake import ValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview recovery of fixed synthetic intake batches"
    )
    parser.add_argument("--batch", choices=BATCH_IDS)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--row", type=int, help="Original one-based record ordinal; requires --batch"
    )
    selection.add_argument(
        "--failed-only", action="store_true", help="Show rejected rows and failed batches"
    )
    parser.add_argument("--json", action="store_true", help="Exact UTF-8 JSON with byte provenance")
    args = parser.parse_args(argv)
    try:
        result = preview_recovery(batch_id=args.batch, row=args.row, failed_only=args.failed_only)
    except ValidationError as exc:
        parser.error(str(exc))
    raw = result.json_bytes() if args.json else result.preview_ar().encode("utf-8")
    sys.stdout.buffer.write(raw)
    return 1 if result.has_failures else 0
