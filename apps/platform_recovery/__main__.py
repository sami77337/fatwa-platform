"""Bounded local synthetic recovery administration; encrypted V11 operations by default."""

import argparse
import json

import django


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "snapshot",
            "verify",
            "restore",
            "backup-status",
            "restore-status",
            "reconcile",
            "rollback",
            "maintenance-init",
            "maintenance-enter",
            "maintenance-status",
            "maintenance-resume",
            "key-create",
            "legacy-snapshot",
            "legacy-verify",
            "legacy-restore",
        ),
    )
    parser.add_argument("--offline-synthetic", action="store_true", required=True)
    for name in (
        "scratch",
        "private-root",
        "pg-bin",
        "bundle",
        "manifest-sha256",
        "ciphertext-sha256",
        "target",
        "key-file",
        "maintenance-root",
        "generation",
        "inspection-sha256",
    ):
        parser.add_argument("--" + name)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    requirements = {
        "snapshot": ("scratch", "private_root", "pg_bin", "key_file", "maintenance_root"),
        "restore": ("scratch", "pg_bin", "bundle", "key_file", "ciphertext_sha256"),
        "verify": ("bundle", "key_file", "ciphertext_sha256"),
        "backup-status": ("bundle",),
        "restore-status": ("target",),
        "reconcile": ("target", "inspection_sha256"),
        "rollback": ("target",),
        "maintenance-init": ("maintenance_root", "private_root"),
        "maintenance-enter": ("maintenance_root",),
        "maintenance-status": ("maintenance_root",),
        "maintenance-resume": ("maintenance_root", "generation"),
        "key-create": ("key_file",),
        "legacy-snapshot": ("scratch", "private_root", "pg_bin"),
        "legacy-restore": ("scratch", "pg_bin", "bundle", "manifest_sha256"),
        "legacy-verify": ("bundle", "manifest_sha256"),
    }
    for name in requirements[args.operation]:
        if getattr(args, name) is None:
            parser.error("required argument: --" + name.replace("_", "-"))
    django.setup()
    from apps.private_media.filesystem import FileSystemStorage

    from . import admin, encrypted, maintenance, service

    def storage():
        return FileSystemStorage(
            service.safe_directory(args.private_root), synthetic_fixtures_only=True
        )

    op = args.operation
    try:
        if op == "key-create":
            result = encrypted.generate_key(path=args.key_file, synthetic_fixtures_only=True)
        elif op == "maintenance-init":
            result = maintenance.initialize(
                root=args.maintenance_root, storage=storage(), synthetic_fixtures_only=True
            )
        elif op == "maintenance-enter":
            result = maintenance.enter(root=args.maintenance_root, synthetic_fixtures_only=True)
        elif op == "maintenance-status":
            result = maintenance.status(root=args.maintenance_root)
        elif op == "maintenance-resume":
            result = maintenance.resume(
                root=args.maintenance_root,
                expected_generation=args.generation,
                confirmed=args.confirm,
                synthetic_fixtures_only=True,
            )
        elif op == "snapshot":
            result = encrypted.snapshot(
                scratch=args.scratch,
                storage=storage(),
                pg_bin=args.pg_bin,
                key_file=args.key_file,
                maintenance_root=args.maintenance_root,
                synthetic_fixtures_only=True,
            )
        elif op == "verify":
            result = encrypted.verify(
                bundle=args.bundle,
                expected_ciphertext_sha256=args.ciphertext_sha256,
                key_file=args.key_file,
            )
        elif op == "restore":
            result = encrypted.restore(
                bundle=args.bundle,
                expected_ciphertext_sha256=args.ciphertext_sha256,
                key_file=args.key_file,
                scratch=args.scratch,
                pg_bin=args.pg_bin,
                synthetic_fixtures_only=True,
            )
        elif op == "backup-status":
            result = encrypted.status(bundle=args.bundle)
        elif op == "restore-status":
            result = admin.inspect_restore(target=args.target, synthetic_fixtures_only=True)
        elif op == "reconcile":
            result = admin.reconcile(
                target=args.target,
                expected_inspection_sha256=args.inspection_sha256,
                confirmed=args.confirm,
                synthetic_fixtures_only=True,
            )
        elif op == "rollback":
            state = service.rollback(target=args.target, synthetic_fixtures_only=True, offline=True)
            result = {"state": state["state"]}
        elif op == "legacy-verify":
            manifest = service.verify_bundle(args.bundle, args.manifest_sha256)
            result = {"verified": True, "tables": len(manifest["baseline"]["tables"])}
        elif op == "legacy-snapshot":
            result = service.snapshot(
                scratch=args.scratch,
                storage=storage(),
                pg_bin=args.pg_bin,
                synthetic_fixtures_only=True,
                offline=True,
            )
        else:
            result = service.restore(
                bundle=args.bundle,
                expected_manifest_sha256=args.manifest_sha256,
                scratch=args.scratch,
                pg_bin=args.pg_bin,
                synthetic_fixtures_only=True,
                offline=True,
            )
        # Restore handles are needed for explicit application startup; never output the nonce.
        result = {
            key: value for key, value in result.items() if key not in {"nonce", "failure_code"}
        }
        print(json.dumps(result, sort_keys=True))
    except (service.RecoveryError, OSError, ValueError) as exc:
        code = (
            str(exc).split(":", 1)[0]
            if isinstance(exc, service.RecoveryError)
            else "operation_failed"
        )
        print(json.dumps({"state": "FAILED", "code": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
