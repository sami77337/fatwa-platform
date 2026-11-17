"""Standalone offline operator entry point; synthetic temporary targets only."""

import argparse
import json

import django


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("snapshot", "verify", "restore", "rollback"))
    parser.add_argument(
        "--offline-synthetic",
        action="store_true",
        required=True,
        help="Confirm application, workers, migrations and GC are stopped",
    )
    parser.add_argument("--scratch", help="Existing owned 0700 directory under /tmp")
    parser.add_argument("--private-root")
    parser.add_argument("--pg-bin")
    parser.add_argument("--bundle")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--target")
    args = parser.parse_args()
    django.setup()
    from apps.private_media.filesystem import FileSystemStorage

    from .service import restore, rollback, safe_directory, snapshot, verify_bundle

    if args.operation == "verify":
        manifest = verify_bundle(args.bundle, args.manifest_sha256)
        result = {"verified": True, "tables": len(manifest["baseline"]["tables"])}
    elif args.operation == "rollback":
        result = rollback(target=args.target, synthetic_fixtures_only=True, offline=True)
    elif args.operation == "snapshot":
        result = snapshot(
            scratch=args.scratch,
            pg_bin=args.pg_bin,
            storage=FileSystemStorage(
                safe_directory(args.private_root), synthetic_fixtures_only=True
            ),
            synthetic_fixtures_only=True,
            offline=True,
        )
    else:
        result = restore(
            bundle=args.bundle,
            expected_manifest_sha256=args.manifest_sha256,
            scratch=args.scratch,
            pg_bin=args.pg_bin,
            synthetic_fixtures_only=True,
            offline=True,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
