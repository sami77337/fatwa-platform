"""Explicit local-only CLI; failed validation never writes a normalized export."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .ingest import (
    CONTRACT_VERSION,
    IngestError,
    ValidationError,
    atomic_write,
    canonical_json,
    ingest,
    load_manifest,
    write_export,
)


def _distinct_paths(inputs: list[Path], outputs: list[Path]) -> None:
    """Prevent outputs from clobbering input, manifest, or each other."""
    for index, target in enumerate(outputs):
        if target.is_symlink():
            raise IngestError("refusing a symlink output target")
        for other in inputs + outputs[:index]:
            if target.resolve() == other.resolve():
                raise IngestError("output paths must differ from inputs and each other")
            if target.exists() and other.exists() and os.path.samefile(target, other):
                raise IngestError("output paths must not alias input or other artifacts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate book 622 heading metadata locally.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=("synthetic", "real-622"))
    parser.add_argument("--format", choices=("csv", "json", "jsonl"))
    parser.add_argument("--adapter", default="canonical", choices=("canonical", "owner-622-r1"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report all validation issues; never write heading exports.")
    args = parser.parse_args(argv)
    if args.dry_run and args.output is not None:
        parser.error("--dry-run cannot be combined with --output")
    if not args.dry_run and args.output is None:
        parser.error("--output is required unless --dry-run is used")
    try:
        outputs = [p for p in (args.output, args.report) if p is not None]
        _distinct_paths([args.input, args.manifest], outputs)
    except (IngestError, OSError) as exc:
        # Do not write any report when its destination would overwrite source.
        sys.stdout.buffer.write(canonical_json({"valid": False, "error": str(exc),
                                               "code": "UNSAFE_OUTPUT_PATH"}))
        return 1
    try:
        manifest = load_manifest(args.manifest)
        result = ingest(args.input, manifest, profile=args.profile,
                        file_format=args.format, input_adapter=args.adapter,
                        strict=not args.dry_run)
        report = dict(result.report)
        report["export_status"] = "NOT_WRITTEN"
        if not args.dry_run:
            write_export(result, args.output)
            report["export_status"] = "WRITTEN"
        exit_code = 0 if report["valid"] else 1
    except ValidationError as exc:
        report = {**exc.report, "export_status": "NOT_WRITTEN"}
        exit_code = 1
    except (IngestError, OSError) as exc:
        report = {
            "contract_version": CONTRACT_VERSION,
            "valid": False, "code": "INPUT_OR_OUTPUT_ERROR", "error": str(exc),
            "export_status": "NOT_WRITTEN", "real_source_acceptance": "NOT_PASSED",
            "deployment_status": "NOT_DEPLOYED", "gates": "GATES_HOLD_PHASE01_BLOCKED",
        }
        exit_code = 1
    try:
        if args.report is not None:
            atomic_write(args.report, canonical_json(report))
    except (IngestError, OSError) as exc:
        sys.stderr.write(f"Unable to write audit report: {exc}\n")
        exit_code = 1
    sys.stdout.buffer.write(canonical_json(report))
    return exit_code
