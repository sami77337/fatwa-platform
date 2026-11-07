"""Launch the local synthetic source reading desk on 127.0.0.1:8017."""

import argparse
import os
import re
import secrets
import sys
from hashlib import sha256
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Start a persistent training journal in .local/reviewer-desk.",
    )
    args = parser.parse_args()
    settings_name = "apps.editorial_workbench.reviewer_settings"
    if (
        os.environ.get("FATWA_PRODUCTION", "0") != "0"
        or os.environ.get("DJANGO_SETTINGS_MODULE", settings_name) != settings_name
    ):
        parser.error("Use a separate development shell for the local reviewer desk.")
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_name

    import django

    django.setup()
    from apps.editorial_followup.__main__ import FollowupPreview
    from apps.fast9_case_source_join.source_history import sample_source_events
    from apps.fast9_case_source_join.source_journal import append_source_event

    secret_env = "FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256"
    if secret_env in os.environ:
        if not re.fullmatch(r"[0-9a-f]{64}", os.environ[secret_env]):
            parser.error("Expected a lowercase SHA-256 digest for the training reviewer.")
    elif sys.stderr.isatty():
        token = secrets.token_hex(32)
        os.environ[secret_env] = sha256(token.encode("ascii")).hexdigest()
        print(f"Temporary training reviewer token: {token}", file=sys.stderr, flush=True)
    else:
        parser.error(
            "Start from an interactive terminal or configure the training reviewer's token digest."
        )

    directory_env = "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR"
    if args.demo:
        if os.environ.get(directory_env):
            parser.error("Use --demo or an existing configured directory, not both.")
        directory = Path(__file__).resolve().parents[2] / ".local" / "reviewer-desk"
        directory.parent.mkdir(mode=0o700, exist_ok=True)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            (event,) = sample_source_events("intake-7", "received")
            append_source_event(directory, event, synthetic_fixtures_only=True)
        os.environ[directory_env] = str(directory)
    else:
        directory = Path(os.environ.get(directory_env, ""))
    if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
        parser.error("Supply an absolute local journal directory, or start with --demo.")
    print("Open http://127.0.0.1:8017/review/", flush=True)
    FollowupPreview().run_from_argv(["reviewer-desk", "runserver", "127.0.0.1:8017", "--noreload"])


if __name__ == "__main__":
    main()
