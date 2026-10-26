"""python -m apps.editorial_export: explicit synthetic offline export/replay."""

import argparse
import os
import stat
import sys
from pathlib import Path

from . import services
from .comparison import compare_exports
from .services import ExportError, build_export, require_development, verify_export


def _regular_file(path: Path) -> bool:
    metadata = path.lstat()
    # Windows junctions and other reparse points are not trusted export inputs.
    return stat.S_ISREG(metadata.st_mode) and not (
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def read_bundle(directory: Path) -> dict[str, bytes]:
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or (
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise ExportError("export: regular_directory_required")
    # Bound enumeration too; never recurse or discover source input files.
    with os.scandir(directory) as entries:
        names = []
        for entry in entries:
            names.append(entry.name)
            if len(names) > len(services.FILE_NAMES):
                raise ExportError("export: unexpected_files")
    if set(names) != set(services.FILE_NAMES):
        raise ExportError("export: unexpected_files")
    files, total = {}, 0
    for name in services.FILE_NAMES:
        path = directory / name
        if not _regular_file(path) or path.stat().st_size > services.MAX_FILE_BYTES:
            raise ExportError("export: invalid_file_size_or_type")
        with path.open("rb") as stream:
            raw = stream.read(services.MAX_FILE_BYTES + 1)
        total += len(raw)
        if len(raw) > services.MAX_FILE_BYTES or total > services.MAX_BUNDLE_BYTES:
            raise ExportError("export: byte_limit")
        files[name] = raw
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline synthetic editorial exports; NOT_DEPLOYED"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, option in (("export", "--output"), ("verify", "--input")):
        command = commands.add_parser(name)
        command.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
        command.add_argument(option, type=Path, required=True)
    compare = commands.add_parser(
        "compare", help="Compare two bundles after exact synthetic replay"
    )
    compare.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True, help="New comparison JSON file")
    args = parser.parse_args(argv)
    try:
        require_development(args.synthetic_fixtures_only)
        if args.command == "export":
            bundle = build_export(synthetic_fixtures_only=True)
            # Complete validation before writing. An existing directory, even
            # empty, is never reused. Each file is exclusive-create as well.
            args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
            for name, raw in bundle.files:
                with (args.output / name).open("xb") as stream:
                    stream.write(raw)
            print("EXPORTED: 4 files; synthetic fixtures only; NOT_DEPLOYED")
        elif args.command == "verify":
            verify_export(read_bundle(args.input), synthetic_fixtures_only=True)
            print("VERIFIED: exact synthetic replay; NOT_DEPLOYED")
        else:
            # Validate both inputs and encode the complete bounded report before
            # touching output. Never add a fifth file to either input bundle.
            if args.output.parent.resolve() in (args.before.resolve(), args.after.resolve()):
                raise ExportError("compare: output_inside_input")
            raw = compare_exports(
                read_bundle(args.before), read_bundle(args.after), synthetic_fixtures_only=True
            )
            with args.output.open("xb") as stream:
                stream.write(raw)
            print("COMPARED: both inputs verified; synthetic fixtures only; NOT_DEPLOYED")
    except (ExportError, OSError):
        # Do not echo arbitrary filesystem paths or fixture contents. An I/O
        # failure may leave a new partial directory; replay rejects it. Never
        # remove files or retry by overwriting: choose a fresh output directory.
        print(
            "Export failed: guard, bounds, replay or filesystem check. Use a new output path for export or comparison.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
