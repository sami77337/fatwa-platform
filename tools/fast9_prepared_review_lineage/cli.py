"""Read only explicit synthetic bundles, emit one evidence record to stdout."""

import argparse
import os
import stat
import sys
from pathlib import Path

from apps.editorial_export import services as exports
from apps.fast8_prepared_review import services as prepared
from apps.fast8_review_export import services as review
from apps.fast9_prepared_review_lineage.services import (
    SCHEMA,
    LineageError,
    build_evidence,
    encode_evidence,
)


def _plain_path(path: Path) -> None:
    for component in (path.absolute(), *path.absolute().parents):
        metadata = component.lstat()
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise LineageError("lineage: linked_path")


def read_bundle(directory: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    """Bound names and bytes; no recursion, archives, links or source discovery."""
    _plain_path(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise LineageError("lineage: regular_directory_required")
    with os.scandir(directory) as entries:
        actual = []
        for entry in entries:
            actual.append(entry.name)
            if len(actual) > len(names):
                raise LineageError("lineage: unexpected_files")
    if set(actual) != set(names):
        raise LineageError("lineage: unexpected_files")
    result, total = {}, 0
    for name in names:
        path = directory / name
        _plain_path(path)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > exports.MAX_FILE_BYTES:
            raise LineageError("lineage: invalid_member")
        with path.open("rb") as stream:
            raw = stream.read(exports.MAX_FILE_BYTES + 1)
        total += len(raw)
        if len(raw) > exports.MAX_FILE_BYTES or total > exports.MAX_BUNDLE_BYTES:
            raise LineageError("lineage: byte_limit")
        result[name] = raw
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only synthetic lineage; NOT_DEPLOYED")
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--case-key", default="batch-synthetic-csv-1")
    parser.add_argument("--scenario", choices=review.SCENARIOS, default="rehearsal")
    parser.add_argument("--source-bundle", type=Path)
    parser.add_argument("--review-bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        exports.require_development(args.synthetic_fixtures_only)
        if args.review_bundle is not None and args.source_bundle is None:
            raise LineageError("lineage: explicit_source_required")
        request = prepared.scenario(args.case_key, synthetic_fixtures_only=True)
        source = read_bundle(args.source_bundle, exports.FILE_NAMES) if args.source_bundle else None
        preview = read_bundle(args.review_bundle, review.FILE_NAMES) if args.review_bundle else None
        record = build_evidence(
            request,
            source_files=source,
            review_files=preview,
            scenario_name=args.scenario,
            synthetic_fixtures_only=True,
        )
        raw = encode_evidence(record)
    except (LineageError, prepared.BridgeError, exports.ExportError, OSError):
        # Never echo a path, input content or raw exception from a rejected file.
        raw = exports.encode_json(
            {
                "schema": SCHEMA,
                "status": "REJECTED",
                "reason": "guard_selector_bundle_or_contract_verification_failed",
                "evidence": None,
                "deployment": "NOT_DEPLOYED",
            }
        )
        sys.stdout.buffer.write(raw)
        return 2
    sys.stdout.buffer.write(raw)
    return 0
