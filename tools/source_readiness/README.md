# Offline source-readiness preflight

Run from the repository root with Python 3.13. This command initializes no Django
settings, uses no database or network client, and writes no input files.

```text
python -m tools.source_readiness
python -m tools.source_readiness --pinned-owner
python -m tools.source_readiness --manifest MANIFEST.json --snapshot SNAPSHOT.json --input SYNTHETIC.json --archive SYNTHETIC.zip
```

All arguments are optional. No manifest or `--pinned-owner` means `NOT_RUN`; other
paths are ignored. `--pinned-owner` uses repository-pinned owner metadata and is
mutually exclusive with `--manifest`. It reports `BLOCKED`, with owner acceptance
and raw evidence checks `NOT_RUN`; it does not open owner source files.
It leaves the local numeric edition ID `null` because that ID is unavailable;
it never invents one. Comparing catalog metadata requires an explicit trusted
manifest and snapshot with the actual local edition ID.
A malformed manifest produces `FAIL` before other files are read.
Raw input and archive files are opened only after a valid manifest identifies
`source_kind` as `synthetic`. With `owner_supplied`, those arguments are ignored
and owner acceptance remains `NOT_RUN`.

Output is one JSON object, with sorted keys, ASCII-escaped Unicode (valid UTF-8),
and a newline. Diagnostics contain fixed codes, never local paths or tracebacks.

| Overall status | Exit code | Meaning |
| --- | --- | --- |
| `PASS` | 0 | Supplied synthetic evidence passed the offline checks. |
| `FAIL` | 1 | Evidence failed validation or an integrity comparison. |
| `BLOCKED` | 2 | Required evidence is unavailable or cannot be safely read. |
| `NOT_RUN` | 3 | No manifest was supplied. |

Files must be regular local files. Symlinks, junctions, device paths, UNC paths,
and drive-relative Windows paths are refused. The manifest limit is 64 KiB;
snapshot, input, and archive limits are each 16 MiB. File failures use fixed
`MANIFEST_`, `SNAPSHOT_`, `INPUT_`, or `ARCHIVE_` codes ending in `UNREADABLE`,
`NOT_REGULAR`, or `TOO_LARGE`. Invalid arguments produce `CLI_ARGUMENTS_INVALID`.
Unavailable or invalid inherited metadata produces
`INHERITED_OWNER_METADATA_INVALID` with `FAIL` (exit 1).

The reusable service is `apps.source_readiness.service.preflight`. Its four
arguments are bytes (or `None`), and it performs no I/O. The manifest is an
explicit trusted expectation supplied by the caller, not a cryptographic
signature or an owner approval. Replacing both expectations and evidence cannot
establish authenticity. Only exact comparisons are made; no Arabic normalization
or inferred citation matching is used.

Input contracts reject unknown and duplicate keys, invalid UTF-8, nonfinite JSON
numbers, booleans used as integer IDs, and out-of-bounds inputs:

- Manifest: `schema: fatwa.source-readiness.manifest.v1`, `dataset_id`,
  `source_kind`, `edition_id`, `spec`, and `catalog_checksum`. `spec` has exactly
  the existing `CatalogSpec` fields. The checksum uses existing
  `prepare_catalog` canonicalization. Synthetic namespaces and edition keys must
  start with `synthetic-`. `edition_id` is a positive integer; owner metadata may
  use `null` only to represent an unavailable local identity.
- Snapshot: `schema: fatwa.source-readiness.snapshot.v1`, `edition_id`, `spec`,
  and `records` containing all existing `HeadingRecord` fields, including an
  explicit nullable `source_entry_number`.
- Raw synthetic input: `schema: fatwa.source-readiness.rows.v1`, `identity`, and
  `records`. `identity` contains the eight textual `CatalogSpec` fields, excluding
  the two hashes and three expected counts. Rows must match the snapshot exactly,
  including original titles, IDs, source order, parents and printed locations.
- Synthetic ZIP: exactly one member named by `spec.input_name`, containing the
  exact raw input bytes, using STORED or DEFLATED compression. Other codecs are
  rejected before decompression. No extraction occurs. Both whole-file hashes must match
  before the member is inspected.

`catalog_metadata` and `catalog_integrity` check only supplied metadata.
`input_sha256` and `archive_sha256` hash actual supplied synthetic bytes.
`source_rows`, `hierarchy`, and `printed_location` require raw input evidence.
Printed-location checks validate explicit part/page values and consistency of
each source page ID, not page images or scholarly citation suitability.
Any failed check takes precedence over missing prerequisites. A valid manifest
with absent evidence produces `BLOCKED`, with unexecuted checks `NOT_RUN`.

To exercise a generated fixture without storing source artifacts in the repository,
run the following in Python from the repository root:

```python
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.source_readiness.fixtures import bundle, encode

manifest, snapshot, raw, archive = bundle()
with tempfile.TemporaryDirectory(prefix="synthetic-readiness-") as directory:
    args = []
    for name, content in (
        ("manifest", encode(manifest)),
        ("snapshot", encode(snapshot)),
        ("input", raw),
        ("archive", archive),
    ):
        path = Path(directory) / name
        path.write_bytes(content)
        args.extend(("--" + name, str(path)))
    result = subprocess.run([sys.executable, "-m", "tools.source_readiness", *args])
    assert result.returncode == 0
```

This fixture is fabricated and is not owner evidence. A synthetic `PASS` does not
accept book 622 originals, pass product gates, authorize import, publish anything,
or approve deployment. `NOT_DEPLOYED / GATES_HOLD` remains in effect.

Focused executable checks:

```text
python -m unittest tests.source_readiness.test_service tests.source_readiness.test_cli tests.reference.test_records tests.reference_links.test_resolution tests.reference_links.test_bridge tests.research_bridge.test_services -v
```

Existing CI workflows are outside this lane's ownership and were not modified.
The integrating lane must include the new readiness tests in its CI selection.
