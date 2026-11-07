"""Record or inspect a single synthetic message event in the local development journal."""

import argparse
import json
import os
import re
import sys
from hashlib import sha256
from pathlib import Path

from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.source_journal import (
    append_source_event,
    history_digest,
    read_source_history,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--synthetic-fixtures-only", action="store_true", required=True)
    parser.add_argument("--case-key", choices=("intake-1", "intake-4", "intake-7"), required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("show", help="Read the saved history.")
    write = commands.add_parser(
        "record", help="Apply one event; its predecessor must already be recorded."
    )
    write.add_argument("sample", choices=("received", "corrected", "deleted", "restored"))
    verify = commands.add_parser(
        "verify", help="Check a saved prefix against a separately retained receipt."
    )
    verify.add_argument("count", type=int)
    verify.add_argument("digest")
    args = parser.parse_args(argv)
    if args.action == "verify" and (
        not 1 <= args.count <= 128 or not re.fullmatch("[0-9a-f]{64}", args.digest)
    ):
        parser.error("verify expects a count from 1 to 128 and a lowercase SHA-256 digest")
    directory = Path(os.environ.get("FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR", ""))
    if not directory.is_absolute():
        parser.error("FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR must specify an absolute directory")
    try:
        if args.action == "record":
            event = sample_source_events(args.case_key, args.sample)[-1]
            history = append_source_event(directory, event, synthetic_fixtures_only=True)
        else:
            history = read_source_history(directory, args.case_key, synthetic_fixtures_only=True)
            if args.action == "verify" and (
                len(history) < args.count or history_digest(history[: args.count]) != args.digest
            ):
                raise ValueError("saved_checkpoint_not_found")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    result = {
        "case_key": args.case_key,
        "status": "HISTORY_PRESENT" if history else "NO_SAVED_HISTORY",
        "checkpoint": {"count": len(history), "sha256": history_digest(history)}
        if history
        else None,
        "events": [
            {
                "id": event.event_id,
                "kind": event.kind,
                "predecessor": event.prior_event_id,
                "question_sha256": sha256(event.body_utf8).hexdigest()
                if event.body_utf8 is not None
                else None,
            }
            for event in history
        ],
    }
    if args.action == "verify":
        result["verified_prefix"] = {"count": args.count, "sha256": args.digest}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
