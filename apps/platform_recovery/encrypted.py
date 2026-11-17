"""Bounded whole-bundle authenticated encryption using cryptography's Fernet recipe.

The existing capture/validation/restore engine is reused. Plaintext archive bytes
stay in memory and pg_restore receives stdin; no unpack/extract or plaintext
backup staging directory is created. Target private files are intentionally
restored plaintext through the existing private storage adapter.
"""

import base64
import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from . import service
from .maintenance import frozen

FORMAT = "fatwa-recovery-fernet-v1"
MAX_TOKEN_BYTES = 64 * 1024 * 1024


def _key(path, *, forbidden=()):
    path = Path(path)
    service.safe_directory(path.parent)
    service.require(path == path.resolve(strict=True), "key_path_invalid")
    for directory in forbidden:
        service.require(not path.is_relative_to(Path(directory).resolve()), "key_inside_artifacts")
    raw = service.read_file(path)
    service.require(len(raw) == 44, "fernet_key_invalid")
    try:
        return Fernet(raw)
    except (ValueError, TypeError):
        raise service.RecoveryError("fernet_key_invalid") from None


def generate_key(*, path, synthetic_fixtures_only=False):
    service.require(
        synthetic_fixtures_only is True and os.environ.get("FATWA_PRODUCTION") == "0",
        "synthetic_ack_required",
    )
    path = Path(path)
    service.safe_directory(path.parent)
    # Existing key files are never overwritten. The caller supplies a distinct key directory.
    service.write_file(path, Fernet.generate_key())
    service.sync_directory(path.parent)
    return {"key_created": True, "algorithm": "Fernet"}


def snapshot(
    *, scratch, storage, pg_bin, key_file, maintenance_root, synthetic_fixtures_only=False
):
    service.guard(synthetic_fixtures_only=synthetic_fixtures_only, offline=True)
    parent = service.safe_directory(scratch)
    cipher = _key(key_file, forbidden=(parent, storage.root, maintenance_root))
    files = {}
    with frozen(root=maintenance_root, storage=storage) as generation:
        capture = service.snapshot(
            scratch=parent,
            storage=storage,
            pg_bin=pg_bin,
            synthetic_fixtures_only=True,
            offline=True,
            _capture=files,
        )
        service.verify_bundle(None, capture["manifest_sha256"], _files=files)
        payload = service.canonical(
            {
                "format": FORMAT,
                "manifest_sha256": capture["manifest_sha256"],
                "maintenance_generation": generation,
                "files": {
                    name: base64.b64encode(raw).decode("ascii") for name, raw in files.items()
                },
            }
        )
        token = cipher.encrypt(payload)
        service.require(len(token) <= MAX_TOKEN_BYTES, "encrypted_drill_size_limit")
        # Verify before publishing the only durable backup representation.
        service.require(cipher.decrypt(token) == payload, "encryption_verification_failed")
        bundle = Path(tempfile.mkdtemp(prefix="sealed-", dir=parent))
        service.write_file(bundle / "backup.fernet", token)
        service.sync_directory(bundle)
        service.checkpoint("encrypted_before_complete")
        service.write_file(bundle / "COMPLETE", service.digest(token).encode())
        service.sync_directory(bundle)
        service.sync_directory(parent)
    return {
        "bundle": str(bundle),
        "ciphertext_sha256": service.digest(token),
        "algorithm": "Fernet",
        "state": "SEALED",
    }


def _token(bundle, expected_ciphertext_sha256):
    bundle = service.safe_directory(bundle)
    service.require(
        type(expected_ciphertext_sha256) is str
        and service.DIGEST.fullmatch(expected_ciphertext_sha256),
        "ciphertext_pin_required",
    )
    service.require(
        set(os.listdir(bundle)) == {"backup.fernet", "COMPLETE"}, "sealed_inventory_invalid"
    )
    service.require(
        (bundle / "backup.fernet").lstat().st_size <= MAX_TOKEN_BYTES, "encrypted_drill_size_limit"
    )
    token = service.read_file(bundle / "backup.fernet")
    service.require(
        service.digest(token) == expected_ciphertext_sha256
        and service.read_file(bundle / "COMPLETE") == expected_ciphertext_sha256.encode(),
        "ciphertext_integrity_failed",
    )
    return token


def _open(bundle, expected_ciphertext_sha256, key_file, *, forbidden=()):
    token = _token(bundle, expected_ciphertext_sha256)
    cipher = _key(key_file, forbidden=(Path(bundle).parent, *forbidden))
    try:
        payload = cipher.decrypt(token)
    except InvalidToken:
        raise service.RecoveryError("backup_authentication_failed") from None
    try:
        data = json.loads(payload)
        service.require(data["format"] == FORMAT, "encrypted_format_invalid")
        files = {name: base64.b64decode(raw, validate=True) for name, raw in data["files"].items()}
        manifest = service.verify_bundle(None, data["manifest_sha256"], _files=files)
    except (ValueError, KeyError, TypeError):
        raise service.RecoveryError("encrypted_payload_invalid") from None
    return files, data["manifest_sha256"], manifest


def verify(*, bundle, expected_ciphertext_sha256, key_file):
    _, _, manifest = _open(bundle, expected_ciphertext_sha256, key_file)
    return {
        "state": "VERIFIED",
        "algorithm": "Fernet",
        "tables": len(manifest["baseline"]["tables"]),
        "external_objects": len(
            {i["key"] for i in manifest["references"] if i["backend"] == service.BACKEND}
        ),
    }


def restore(
    *, bundle, expected_ciphertext_sha256, key_file, scratch, pg_bin, synthetic_fixtures_only=False
):
    service.guard(synthetic_fixtures_only=synthetic_fixtures_only, offline=True)
    parent = service.safe_directory(scratch)
    files, pin, _ = _open(bundle, expected_ciphertext_sha256, key_file, forbidden=(parent,))
    # Authentication and complete manifest/inventory verification precede CREATE DATABASE.
    return service.restore(
        bundle=None,
        expected_manifest_sha256=pin,
        scratch=parent,
        pg_bin=pg_bin,
        synthetic_fixtures_only=True,
        offline=True,
        _files=files,
    )


def status(*, bundle):
    """Metadata-only local status; never prints keys, paths, manifests or content."""
    bundle = service.safe_directory(bundle)
    if not (bundle / "COMPLETE").exists():
        return {"state": "INCOMPLETE", "authenticated": False}
    try:
        pin = service.read_file(bundle / "COMPLETE").decode("ascii")
        _token(bundle, pin)
    except (OSError, ValueError, service.RecoveryError):
        return {"state": "DAMAGED", "authenticated": False}
    # COMPLETE alone is not independent provenance or authentication without the key.
    return {"state": "SEALED_UNAUTHENTICATED", "authenticated": False, "algorithm": "Fernet"}
