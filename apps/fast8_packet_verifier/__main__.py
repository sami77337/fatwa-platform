"""python -B -m apps.fast8_packet_verifier: bounded read-only verification."""

import argparse
import os
import stat
import sys
from pathlib import Path

from apps.editorial_export.services import MAX_FILE_BYTES
from apps.editorial_workbench.packets import MAX_PACKET_BYTES

from .services import PacketVerificationError, require_development, verify_packet


def _regular(metadata: os.stat_result) -> bool:
    return stat.S_ISREG(metadata.st_mode) and not (
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def read_input(path: Path, limit: int) -> bytes:
    """Explicit regular files only; bounded binary reads preserve original bytes."""
    metadata = path.lstat()
    if not _regular(metadata):
        raise PacketVerificationError("regular_file_required")
    if metadata.st_size > limit:
        raise PacketVerificationError("byte_limit")
    # O_NOFOLLOW/O_NONBLOCK protect POSIX leaf replacement with a symlink/FIFO.
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not _regular(opened) or (opened.st_dev, opened.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise PacketVerificationError("regular_file_required")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise PacketVerificationError("byte_limit")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify one fixed synthetic packet; NOT_DEPLOYED")
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--case-key", required=True)
    args = parser.parse_args(argv)
    try:
        require_development(args.synthetic_fixtures_only)
        receipt = verify_packet(
            read_input(args.packet, MAX_PACKET_BYTES),
            read_input(args.manifest, MAX_FILE_BYTES),
            case_key=args.case_key,
            synthetic_fixtures_only=args.synthetic_fixtures_only,
        )
    except PacketVerificationError as exc:
        print(exc.code, file=sys.stderr)
        return 1
    except OSError:
        print("packet_verify: input_io_error", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
