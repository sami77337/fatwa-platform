"""Bound local file reads before handing bytes to the offline preflight service."""

import argparse
import json
import ntpath
import os
import stat
import sys
from pathlib import Path, PureWindowsPath

from apps.source_readiness.service import error_report, parse_manifest, preflight

MANIFEST_LIMIT = 64 * 1024
FILE_LIMIT = 16 * 1024 * 1024
EXIT_CODES = {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "NOT_RUN": 3}


class ReadError(ValueError):
    """Carry a fixed diagnostic code without retaining local path information."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ReadError("CLI_ARGUMENTS_INVALID")


def read_local(path_text: str, label: str, limit: int) -> bytes:
    """Read a bounded regular local file; reject links and Windows device paths."""
    windows_path = PureWindowsPath(path_text)
    if (
        path_text.startswith(("\\", "//"))
        or (windows_path.drive and not windows_path.root)
        or ntpath.isreserved(path_text)
    ):
        raise ReadError(f"{label}_NOT_REGULAR")
    path = Path(path_text).absolute()
    try:
        for component in (path, *path.parents):
            if component.is_symlink() or component.is_junction():
                raise ReadError(f"{label}_NOT_REGULAR")
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ReadError(f"{label}_NOT_REGULAR")
        if before.st_size > limit:
            raise ReadError(f"{label}_TOO_LARGE")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise ReadError(f"{label}_NOT_REGULAR")
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise ReadError(f"{label}_TOO_LARGE")
        return raw
    except ReadError:
        raise
    except (OSError, ValueError):
        raise ReadError(f"{label}_UNREADABLE") from None


def emit(report) -> int:
    payload = json.dumps(report.as_dict(), ensure_ascii=True, sort_keys=True) + "\n"
    # ASCII escaping is also valid UTF-8 and works under narrow Windows encodings.
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(payload.encode("ascii"))
    else:
        sys.stdout.write(payload)
    return EXIT_CODES[report.status]


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(
        prog="python -m tools.source_readiness",
        description="Offline, development-only source readiness; synthetic raw inputs only.",
        allow_abbrev=False,
    )
    manifest_options = parser.add_mutually_exclusive_group()
    manifest_options.add_argument("--manifest", help="Local UTF-8 source manifest (at most 64 KiB)")
    manifest_options.add_argument(
        "--pinned-owner",
        action="store_true",
        help="Use repository-pinned owner metadata without opening owner source files",
    )
    parser.add_argument("--snapshot", help="Local redacted readiness snapshot")
    parser.add_argument("--input", help="Local synthetic input; requires a synthetic manifest")
    parser.add_argument("--archive", help="Local synthetic ZIP; requires a synthetic manifest")
    try:
        args = parser.parse_args(argv)
        if args.manifest is None and not args.pinned_owner:
            return emit(preflight(None))
        if args.pinned_owner:
            from apps.source_readiness.pins import pinned_owner_manifest

            try:
                manifest = pinned_owner_manifest()
            except (OSError, ValueError):
                return emit(error_report("INHERITED_OWNER_METADATA_INVALID", status="FAIL"))
        else:
            manifest = read_local(args.manifest, "MANIFEST", MANIFEST_LIMIT)
        try:
            parsed = parse_manifest(manifest)
        except ValueError:
            return emit(preflight(manifest))
        snapshot = read_local(args.snapshot, "SNAPSHOT", FILE_LIMIT) if args.snapshot else None
        input_bytes = archive_bytes = None
        if parsed["source_kind"] == "synthetic":
            if args.input:
                input_bytes = read_local(args.input, "INPUT", FILE_LIMIT)
            if args.archive:
                archive_bytes = read_local(args.archive, "ARCHIVE", FILE_LIMIT)
        return emit(preflight(manifest, snapshot, input_bytes, archive_bytes))
    except ReadError as error:
        return emit(error_report(str(error)))
