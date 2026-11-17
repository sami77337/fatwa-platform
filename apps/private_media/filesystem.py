"""Owned synthetic filesystem originals with no public path, overwrite or cloud endpoint.

Binding writers hold the digest lock around the *outermost* database transaction.
Garbage collection takes the same lock before its fresh reference callback. This
orders file deletion against reference commit without holding database locks in GC.
"""

import ctypes
import errno
import math
import os
import re
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

from .storage import PrivateStorage, StoredOriginal, verify_original
from .validation import MAX_BYTES, MediaValidationError, ValidatedMedia

BACKEND = "private-filesystem-v1"
_DIGEST = re.compile(r"[a-f0-9]{64}")
_KEY = re.compile(r"([a-f0-9]{64})\.blob")
_MARKER = b"fatwa-private-media-v1\nSYNTHETIC_ONLY\n"
_LOCAL = threading.local()


def _fail(code="private_storage_unavailable"):
    raise MediaValidationError(code)


def _digest(value):
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        _fail("private_storage_reference_invalid")
    return value


def _check_stat(value, *, directory=False, mode=0o400):
    if (
        not (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode))
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != mode
        or (not directory and value.st_nlink != 1)
    ):
        _fail("private_storage_permissions_invalid")


@contextmanager
def _open_directory(path, *, create=False):
    """Walk from / with directory FDs, rejecting symlinks in every component."""
    parts = Path(path).parts
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, name in enumerate(parts[1:]):
            if create and index == len(parts) - 2:
                try:
                    os.mkdir(name, 0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = next_descriptor
        _check_stat(os.fstat(descriptor), directory=True, mode=0o700)
        yield descriptor
    finally:
        os.close(descriptor)


def _install_no_replace(directory, source, target, *, target_directory=None):
    # Linux renameat2 makes visibility atomic without a hardlink crash window and
    # rejects a concurrently existing destination instead of overwriting it.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        _fail("private_storage_atomic_install_unavailable")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if (
        rename(
            directory,
            os.fsencode(source),
            directory if target_directory is None else target_directory,
            os.fsencode(target),
            1,
        )
        != 0
    ):
        code = ctypes.get_errno()
        raise OSError(code, "private atomic install failed")


class FileSystemStorage(PrivateStorage):
    def __init__(self, root, *, synthetic_fixtures_only=False):
        if synthetic_fixtures_only is not True or os.environ.get("FATWA_PRODUCTION") != "0":
            _fail("private_storage_synthetic_only")
        path = Path(root)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or any(part in {"static", "media", "public", "www"} for part in path.parts)
        ):
            _fail("private_storage_root_invalid")
        self.root = path
        for name in ("STATIC_ROOT", "MEDIA_ROOT"):
            public = getattr(settings, name, None)
            if public and path.is_relative_to(Path(public).absolute()):
                _fail("private_storage_root_invalid")
        try:
            with _open_directory(self.root, create=True) as rootfd:
                names = os.listdir(rootfd)
                if not names:
                    marker = os.open(
                        ".private-media-v1",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=rootfd,
                    )
                    try:
                        os.write(marker, _MARKER)
                        os.fsync(marker)
                    finally:
                        os.close(marker)
                    os.fsync(rootfd)
                marker = os.open(".private-media-v1", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=rootfd)
                try:
                    _check_stat(os.fstat(marker), mode=0o600)
                    if os.read(marker, len(_MARKER) + 1) != _MARKER:
                        _fail("private_storage_root_invalid")
                finally:
                    os.close(marker)
                for name in ("objects", "locks", "quarantine"):
                    try:
                        os.mkdir(name, 0o700, dir_fd=rootfd)
                    except FileExistsError:
                        pass
                    child = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=rootfd
                    )
                    try:
                        _check_stat(os.fstat(child), directory=True, mode=0o700)
                    finally:
                        os.close(child)
                os.fsync(rootfd)
        except OSError as exc:
            raise MediaValidationError("private_storage_unavailable") from exc

    @contextmanager
    def _directory(self, name):
        try:
            with _open_directory(self.root) as rootfd:
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=rootfd
                )
                try:
                    _check_stat(os.fstat(descriptor), directory=True, mode=0o700)
                    yield descriptor
                finally:
                    os.close(descriptor)
        except OSError as exc:
            raise MediaValidationError("private_storage_unavailable") from exc

    @contextmanager
    def binding_lock(self, digest):
        import fcntl

        digest = _digest(digest)
        identity = (os.getpid(), str(self.root), digest)
        held = getattr(_LOCAL, "held", {})
        if identity in held:
            yield
            return
        with self._directory("locks") as directory:
            descriptor = os.open(
                digest + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory
            )
            try:
                _check_stat(os.fstat(descriptor), mode=0o600)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            _fail("private_storage_busy")
                        time.sleep(0.02)
                held[identity] = descriptor
                _LOCAL.held = held
                try:
                    yield
                finally:
                    held.pop(identity, None)
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _reference(self, original):
        if (
            not isinstance(original, StoredOriginal)
            or original.backend != BACKEND
            or original.inline is not None
            or original.key != _digest(original.sha256) + ".blob"
            or type(original.size) is not int
            or not 1 <= original.size <= MAX_BYTES
        ):
            _fail("private_storage_reference_invalid")
        return original

    def _read(self, directory, original):
        descriptor = os.open(original.key, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            _check_stat(info)
            if info.st_size != original.size:
                _fail("private_original_integrity_failed")
            chunks = []
            remaining = original.size + 1
            while remaining:
                part = os.read(descriptor, remaining)
                if not part:
                    break
                chunks.append(part)
                remaining -= len(part)
            return verify_original(b"".join(chunks), original.sha256, original.size)
        finally:
            os.close(descriptor)

    def _write(self, directory, original, raw):
        pending = ".pending-" + secrets.token_hex(16)
        descriptor = os.open(
            pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        try:
            remaining = memoryview(raw)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError(errno.EIO, "private write failed")
                remaining = remaining[written:]
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                _install_no_replace(directory, pending, original.key)
            except FileExistsError:
                # A competing exact original is idempotent; corrupt bytes are never replaced.
                self._read(directory, original)
                os.unlink(pending, dir_fd=directory)
            os.fsync(directory)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(pending, dir_fd=directory)
            except FileNotFoundError:
                pass

    def put(self, media: ValidatedMedia) -> StoredOriginal:
        if (
            not isinstance(media, ValidatedMedia)
            or type(media.size) is not int
            or not 1 <= media.size <= MAX_BYTES
        ):
            _fail("private_storage_reference_invalid")
        verify_original(media.raw, media.sha256, media.size)
        original = StoredOriginal(
            BACKEND, _digest(media.sha256) + ".blob", media.sha256, media.size
        )
        with self.binding_lock(original.sha256), self._directory("objects") as directory:
            try:
                self._read(directory, original)
            except FileNotFoundError:
                self._write(directory, original, media.raw)
            self._read(directory, original)
            descriptor = os.open(original.key, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(directory)
        return original

    def get(self, original: StoredOriginal) -> bytes:
        self._reference(original)
        # Scoped callers may already hold a case DB lock. Taking the digest lock
        # here would invert writers' filesystem-before-database order. Immutable
        # owner references protect against GC; opened FDs remain readable through
        # unlink, and an unbound orphan racing cleanup fails closed if absent.
        with self._directory("objects") as directory:
            return self._read(directory, original)

    def restore(self, original, backup_bytes, *, recover_corrupt=False):
        """Restore exact missing bytes; explicit corruption recovery preserves the damaged file."""
        self._reference(original)
        verify_original(backup_bytes, original.sha256, original.size)
        if type(recover_corrupt) is not bool:
            _fail("private_storage_recovery_invalid")
        with self.binding_lock(original.sha256), self._directory("objects") as directory:
            try:
                self._read(directory, original)
                return {"restored": False, "quarantined": False}
            except FileNotFoundError:
                pass
            except MediaValidationError:
                if not recover_corrupt:
                    raise
                info = os.stat(original.key, dir_fd=directory, follow_symlinks=False)
                # Suspicious links, ownership and permissions are never moved or repaired.
                _check_stat(info)
                with self._directory("quarantine") as quarantine:
                    name = original.key + ".corrupt-" + secrets.token_hex(16)
                    _install_no_replace(directory, original.key, name, target_directory=quarantine)
                    os.fsync(quarantine)
                    os.fsync(directory)
                self._write(directory, original, backup_bytes)
                return {"restored": True, "quarantined": True}
            self._write(directory, original, backup_bytes)
            return {"restored": True, "quarantined": False}

    def collect_orphans(self, is_referenced, *, grace_seconds=86400, dry_run=True):
        """Only valid old unreferenced originals are eligible; defaults are read-only.

        Callback must query all owner models afresh without locks, returning a
        literal bool. Writers must hold binding_lock through reference commit.
        Unknown/corrupt/linked files and callback failures are preserved.
        """
        if (
            not callable(is_referenced)
            or type(grace_seconds) not in (int, float)
            or not math.isfinite(grace_seconds)
            or grace_seconds < 3600
            or type(dry_run) is not bool
        ):
            _fail("private_storage_cleanup_invalid")
        report = []
        with self._directory("objects") as directory:
            for key in sorted(os.listdir(directory)):
                match = _KEY.fullmatch(key)
                if match is None:
                    report.append({"key": key, "status": "UNKNOWN_PRESERVED"})
                    continue
                digest = match.group(1)
                try:
                    with self.binding_lock(digest):
                        info = os.stat(key, dir_fd=directory, follow_symlinks=False)
                        _check_stat(info)
                        if not 1 <= info.st_size <= MAX_BYTES:
                            _fail("private_original_integrity_failed")
                        original = StoredOriginal(BACKEND, key, digest, info.st_size)
                        self._read(directory, original)
                        if time.time() - info.st_mtime < grace_seconds:
                            report.append({"key": key, "status": "GRACE_PRESERVED"})
                            continue
                        try:
                            referenced = is_referenced(original)
                        except Exception:
                            report.append({"key": key, "status": "REFERENCE_UNAVAILABLE_PRESERVED"})
                            continue
                        if type(referenced) is not bool:
                            raise ValueError("reference callback must return bool")
                        if referenced:
                            status = "REFERENCED_PRESERVED"
                        elif dry_run:
                            status = "WOULD_REMOVE"
                        else:
                            os.unlink(key, dir_fd=directory)
                            try:
                                os.fsync(directory)
                                status = "REMOVED"
                            except OSError:
                                status = "REMOVED_DURABILITY_UNCONFIRMED"
                        report.append({"key": key, "status": status})
                except (OSError, ValueError):
                    report.append({"key": key, "status": "UNVERIFIED_PRESERVED"})
        return report
