"""Bounded JSON input and UTF-8 stdout only; no persistent output adapter."""

import argparse
import json
import sys
from hashlib import sha256
from typing import BinaryIO

from apps.workflow_invariants.engine import (
    MAX_INPUT_BYTES,
    ReplayError,
    canonical_bytes,
    replay,
    scenario,
)


def _object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReplayError("input: duplicate_key")
        result[key] = value
    return result


def _invalid_number(value: str) -> None:
    raise ReplayError("input: unsupported_number")


def load_request(stream: BinaryIO) -> tuple[dict, str]:
    raw = stream.read(MAX_INPUT_BYTES + 1)
    if not 1 <= len(raw) <= MAX_INPUT_BYTES:
        raise ReplayError("input: byte_limit")
    try:
        request = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=_invalid_number,
            parse_float=_invalid_number,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ReplayError("input: invalid_json_or_unicode") from exc
    return request, sha256(raw).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline fixed-synthetic workflow replay")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input", help="UTF-8 JSON command file, or - for stdin")
    inputs.add_argument(
        "--scenario", choices=("rehearsal", "preparation", "blocked"), default="rehearsal"
    )
    parser.add_argument(
        "--emit-fixture",
        action="store_true",
        help="Emit a built-in command envelope instead of replaying",
    )
    parser.add_argument(
        "--fail-on-rejection",
        action="store_true",
        help="Exit 1 if any event is rejected (default: report with exit 0)",
    )
    args = parser.parse_args(argv)
    try:
        if args.emit_fixture and args.input:
            raise ReplayError("input: emit_requires_builtin_scenario")
        raw_hash = None
        if args.input == "-":
            request, raw_hash = load_request(sys.stdin.buffer)
        elif args.input:
            with open(args.input, "rb") as stream:
                request, raw_hash = load_request(stream)
        else:
            request = scenario(args.scenario)
        result = request if args.emit_fixture else replay(request)
        if raw_hash is not None:
            result["input_bytes_sha256"] = raw_hash
        sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
        return int(
            bool(
                args.fail_on_rejection
                and not args.emit_fixture
                and any(not step["accepted"] for step in result["steps"])
            )
        )
    except (ReplayError, OSError) as exc:
        # Do not echo input content or paths (which could contain private labels).
        reason = str(exc) if isinstance(exc, ReplayError) else "input: io_error"
        status = "INVARIANT_FAILURE" if reason.startswith("invariant:") else "INVALID_INPUT"
        sys.stderr.buffer.write(canonical_bytes({"status": status, "reason": reason}) + b"\n")
        return 3 if status == "INVARIANT_FAILURE" else 2
