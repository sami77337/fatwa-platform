# Bounded private media primitives

`validation.validate(raw, filename, media_type)` returns a frozen `ValidatedMedia`
with exact original bytes, filename, canonical MIME, SHA-256, size, kind and
parser metadata. Failure raises `MediaValidationError` with a fixed safe code.
No content is rewritten. No authority, case, answer, publication or delivery is
created here. Callers retain their separate domain bindings and authorize reads.

Supported fabricated files: UTF-8 text ≤65536 bytes; PDF/JPEG/PNG/WebP/MP3/M4A/WAV
≤192000 bytes. The surrounding existing request guard remains 256KiB.

Validation runs in a Python worker process: six-second wall timeout, POSIX
three-second CPU and 256MiB address-space limits. Pillow 13.0.0 verifies and loads
single-frame images ≤4 million pixels. pypdf 7.1.0 parses strict PDFs ≤10 pages,
bounded graph depth/count and decoded streams; encrypted documents, actions,
external links, forms, scripts, embedded files and active media are rejected.
mutagen 1.48.1 parses MP3/M4A metadata; M4A atoms must bound one audio-only track,
with AAC codec. WAV uses `wave` with complete PCM-frame count and RIFF length.
Audio is limited to stereo, 8–96kHz and 120 seconds. This is structural admission,
**not malware scanning, a safety certification or full audio decoding**.

`storage.PrivateStorage.put/get` remains the private adapter contract. The default
`InlineDatabaseStorage` preserves V8 behavior. V9 adds an actual Linux
`filesystem.FileSystemStorage(root, synthetic_fixtures_only=True)` adapter outside
PostgreSQL. It additionally requires `FATWA_PRODUCTION=0`; no root/default/backend
is activated automatically. `FATWA_PRIVATE_MEDIA_STORAGE` accepts a trusted server
adapter object. `read_original(StoredOriginal(...))` reads legacy inline rows with
the inline adapter even after filesystem storage is configured.

Filesystem originals have backend `private-filesystem-v1`, key `<sha256>.blob`,
`inline=None`, and unchanged SHA/size. Root/child directories are owner-only0700;
originals0400 and lock/marker files0600. The adapter rejects symlinks in all path
components, wrong ownership/permissions, hardlinked originals, traversal keys,
known public/static/media directories, nonempty unmarked roots, and invalid
references. New originals are written to exclusive private temporary files,
fsynced, atomically installed with Linux `renameat2(RENAME_NOREPLACE)`, and their
directory fsynced. Existing exact originals are idempotent; different bytes are
never silently overwritten. Every read verifies exact bytes/size/hash. No URL or
filename from an upload becomes a filesystem path.

## Binding, migration and cleanup contract

Writers and inline-to-filesystem conversions must take `storage.binding_lock(sha)`
**before** any owner/case database locks and hold it through the outermost DB
transaction's commit. Multiple digests require sorted lock order. Inline storage
implements the same context manager as a no-op. The filesystem lock is reentrant
per thread and uses `flock` across processes. Reads intentionally do not take this
lock: scoped reads may already hold a case DB lock, so acquiring a digest lock
would invert writer ordering. Reads use immutable open descriptors and integrity
checks; live owner references prevent GC, while a racing unbound orphan may fail
closed as missing. Example:

```python
with storage.binding_lock(media.sha256):
    with transaction.atomic(durable=True):
        stored = storage.put(media)
        assert storage.get(stored) == media.raw
        # Persist the owner's immutable backend/key/hash/size binding here.
```

The parent campaign owns database fields, narrow conversion triggers and conversion
audits in the attachment/answer domains. This module never mutates a case or
answer, creates parallel records, changes media validation, or grants access.

`collect_orphans(is_referenced, grace_seconds=86400, dry_run=True)` is read-only by
default and enforces a minimum3600-second grace. Each candidate takes the same
binding lock, revalidates bytes/permissions, then invokes a **fresh** callback
checking all live owner references without database locks. Callback errors,
non-bool replies, referenced/recent files, corrupt bytes, symlinks, hardlinks,
unknown filenames and crash-left pending files are preserved. Only valid old
unreferenced originals are removed with `dry_run=False`. Lockfiles are retained
to preserve lock identity. Reports distinguish dry-run, preserved and removed
states; a directory-fsync failure after unlink is explicitly
`REMOVED_DURABILITY_UNCONFIRMED`, never mislabeled as preserved. Maintenance
should run against the same root, provider and reference callback as writers.

`restore(original, backup_bytes)` accepts only the exact expected digest/size and
restores a missing original. It does not alter owner records or metadata. With
explicit `recover_corrupt=True`, a regular privately-owned damaged original is
atomically moved into private quarantine before replacement; links or permission
anomalies are never moved. If replacement fails, quarantine retains damaged bytes
and a subsequent exact-backup retry can restore the missing original. Read/hash
failures do not fall back to another source. Backups must be supplied through a
trusted bounded caller; no network/cloud backup integration is configured.

Disk-full, file/directory fsync failure, corruption, missing bytes, restore retry,
legacy reads, cross-process locks, concurrent writers and cleanup concurrency
are tested with owned temporary directories. This is actual private local storage,
not production object storage, antivirus scanning or deployment. Linux fcntl and
renameat2 are required; unsupported platforms fail closed. Crash-left `.pending-*`
files remain private for operator investigation rather than speculative deletion.

`fixtures.synthetic_files()` produces all eight test formats. Images are 16×12
solid color, PDF is one blank page, WAV is silence, and committed MP3/M4A fixtures
are a 0.2-second generated 440Hz sine. Generated using installed ffmpeg 7.1.5:

```sh
ffmpeg -f lavfi -i sine=frequency=440:duration=0.2 -ar 22050 -ac 1 -codec:a libmp3lame -b:a 32k synthetic.mp3
ffmpeg -f lavfi -i sine=frequency=440:duration=0.2 -ar 22050 -ac 1 -codec:a aac -b:a 32k -movflags +faststart synthetic.m4a
```

ffmpeg is not a runtime dependency. Python package versions were verified from
the publishers' PyPI metadata; pins are integrated by the campaign parent.
No production configuration, external sending or AI ruling is included.
NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.
