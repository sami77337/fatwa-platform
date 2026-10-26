"""Read an immutable synthetic export; create or verify a separate preview."""

import argparse
import os
import stat
import sys
from pathlib import Path

from apps.editorial_export import services as exports
from apps.editorial_export.__main__ import read_bundle
from apps.fast8_review_export.services import (
    FILE_NAMES,
    SCENARIOS,
    build_preview,
    verify_preview,
)
from apps.workflow_invariants.engine import ReplayError


def _plain_path(path: Path) -> None:
    """Reject symlinks and Windows reparse points in all existing components."""
    for component in (path.absolute(), *path.absolute().parents):
        metadata = component.lstat()
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise exports.ExportError("review_preview: linked_path")


def _read_preview(directory: Path) -> dict[str, bytes]:
    _plain_path(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise exports.ExportError("review_preview: regular_directory_required")
    with os.scandir(directory) as entries:
        names = []
        for entry in entries:
            names.append(entry.name)
            if len(names) > len(FILE_NAMES):
                raise exports.ExportError("review_preview: unexpected_files")
    if set(names) != set(FILE_NAMES):
        raise exports.ExportError("review_preview: unexpected_files")
    files, total = {}, 0
    for name in FILE_NAMES:
        path = directory / name
        _plain_path(path)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > exports.MAX_FILE_BYTES:
            raise exports.ExportError("review_preview: invalid_file_size_or_type")
        with path.open("rb") as stream:
            raw = stream.read(exports.MAX_FILE_BYTES + 1)
        total += len(raw)
        if len(raw) > exports.MAX_FILE_BYTES or total > exports.MAX_BUNDLE_BYTES:
            raise exports.ExportError("review_preview: byte_limit")
        files[name] = raw
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline synthetic review evidence; NOT_DEPLOYED")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, option in (("preview", "--output"), ("verify", "--input")):
        command = commands.add_parser(name)
        command.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
        command.add_argument("--source-bundle", type=Path, required=True)
        command.add_argument("--scenario", choices=SCENARIOS, default="rehearsal")
        command.add_argument(option, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        exports.require_development(args.synthetic_fixtures_only)
        _plain_path(args.source_bundle)
        source = read_bundle(args.source_bundle)
        if args.command == "preview":
            _plain_path(args.output.parent)
            if args.output.resolve().is_relative_to(args.source_bundle.resolve()):
                raise exports.ExportError("review_preview: output_inside_source")
            bundle = build_preview(
                source, scenario_name=args.scenario, synthetic_fixtures_only=True
            )
            # No reuse, overwriting, automatic deletion or partial validation.
            args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
            for name, raw in bundle.files:
                with (args.output / name).open("xb") as stream:
                    stream.write(raw)
            print("PREVIEW: 3 files; evidence only; persisted review NOT_CONNECTED; NOT_DEPLOYED")
        else:
            verify_preview(
                _read_preview(args.input),
                source,
                scenario_name=args.scenario,
                synthetic_fixtures_only=True,
            )
            print("VERIFIED: exact synthetic evidence replay; NOT_DEPLOYED")
    except (exports.ExportError, ReplayError, OSError):
        # No paths, source data, external exception text or partial JSON output.
        # Failed new writes may leave a partial preview; verification rejects it.
        print("Review preview failed: guard, bounds, replay or filesystem check.", file=sys.stderr)
        return 1
    return 0
