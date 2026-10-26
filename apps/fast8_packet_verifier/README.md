# Offline single synthetic review-packet verifier

Read-only CLI/service for one **default-selection exported packet** and the
unchanged `editorial_export` manifest from this checkout. This closes the gap
between packet construction and the existing four-file export verifier by
providing stable diagnostics and revision-digest evidence for one pinned case.

It reuses `editorial_workbench.packets.serialize_packet` and
`editorial_export.services.build_export` / `encode_json` / development guards.
The original `verify_export` is unchanged. There are no URLs, settings, database
access, mutations, migrations, archive readers, external services or new deps.

## Run

Python 3.13, repository root, existing dependencies:

```text
python -B -m apps.fast8_packet_verifier --synthetic-fixtures-only --case-key history --packet packet.json --manifest manifest.json
```

Only explicitly fabricated, built-in synthetic fixtures are accepted. Do not
supply owner archives or real/private records. Input paths are explicit regular
files, read as bounded bytes; leaf symlinks/reparse points are rejected. The CLI
does not create or overwrite files. Exit 0 emits canonical JSON bytes to stdout;
exit 1 emits one content-free error code to stderr and no success receipt;
argparse usage errors exit 2. No input content or paths appear in verifier errors.

To produce the two **synthetic** inputs in a new empty directory, use existing
producers (the following example intentionally writes those two fixture files;
the verifier itself never writes):

```python
from pathlib import Path
from apps.editorial_export.services import build_export
from apps.editorial_workbench.packets import serialize_packet

bundle = build_export(synthetic_fixtures_only=True)
entry = next(
    e for e in bundle.report()["cases"] if e["packet"]["identity"]["case_key"] == "history"
)
for name, raw in (
    ("packet.json", serialize_packet(entry["packet"])),
    ("manifest.json", bundle.file("manifest.json")),
):
    with Path(name).open("xb") as stream:
        stream.write(raw)
```

The service returns immutable receipt bytes:

```python
from apps.fast8_packet_verifier.services import verify_packet

receipt = verify_packet(
    packet_bytes, manifest_bytes, case_key="history", synthetic_fixtures_only=True
)
```

## Verification boundary and evidence

- Caller pins the exact `case_key`; external IDs never join records. All identity
  fields, source text, byte offsets and input/source hashes must replay exactly.
- Original byte slices must match their UTF-8 input; parsed-row serialization and
  serialized intake retain their distinct existing provenance semantics.
- Every immutable revision, observation and reference diagnostic must preserve
  its membership, order and full typed values. Receipt revision SHA256 values
  hash `serialize_packet(snapshot)` including its final LF. They are newly
  computed evidence, not invented pre-existing revision-signature fields.
- Packet SHA256 must match its one manifest member. The **entire manifest** must
  match the fixed authoritative export, including ordered case/batch membership
  and file metadata. Coordinated tampering plus rehashing cannot pass replay.
- The receipt identifies packet, manifest and source digests, revision numbers
  and digests, and reference ordinals; it excludes source/question/answer text.
- Packet bounds: 524288 bytes, 4096 nodes, depth 16, 131072 chars per string.
  Manifest uses export bounds: 2 MiB, 100000 nodes, depth 24, same string ceiling.
  Both inherit strict UTF-8 and signed 63-bit magnitude limits. Duplicate JSON
  keys, floats, NaN, invalid Unicode and noncanonical encoding are rejected.
  No normalization, trimming, newline conversion or timestamp rewriting occurs.

This is fixed-version integrity verification, **not** arbitrary import, archive
acceptance, authentication, scholarly approval or persisted event verification.
Only the default revision selection serialized in the export is a member;
custom workbench selections fail `packet_replay_mismatch`. No new historical
manifest format or weaker verification path is introduced.

Other bundle files are NOT_SUPPLIED to this command. Their manifest entries are
replayed, but their on-disk contents are **not verified**. Use the unchanged
`python -B -m apps.editorial_export verify --synthetic-fixtures-only --input DIR`
for full four-file bundle verification. No PostgreSQL/browser acceptance is
claimed by this offline lane.

## Exact failure codes

All codes have the literal prefix `packet_verify: `. The first failing stage
wins; no partial success is emitted. Order: development guard, packet decode,
manifest decode, trusted fixture replay/key selection, packet identity/source,
revisions, observations, references, complete packet replay, manifest membership,
complete manifest replay. CLI file checks precede decoding.

| Code suffix | Meaning |
| --- | --- |
| `synthetic_development_only` | Missing literal-True acknowledgement or production guard |
| `input_io_error`, `regular_file_required` | CLI file access or regular-file constraint |
| `invalid_input_type`, `byte_limit` | Input is not bytes or exceeds inherited bound |
| `invalid_utf8`, `invalid_json`, `duplicate_key`, `invalid_payload` | Wire decoding / root-object rejection |
| `structure_limit`, `text_limit`, `integer_limit`, `unsupported_value` | Authoritative serialization bound/type failure |
| `noncanonical_packet`, `noncanonical_manifest` | Bytes differ from canonical serialization |
| `fixture_replay_unavailable`, `unknown_case` | Fixed fixture replay fails or requested key unavailable |
| `packet_fields_mismatch`, `invalid_contract` | Missing/extra packet fields or malformed nested contract |
| `case_identity_mismatch` | Expected case/source/batch/row identity differs |
| `source_digest_mismatch`, `source_slice_mismatch`, `source_identity_mismatch` | Source hashes, original byte slice or exact provenance differs |
| `revision_missing`, `revision_extra`, `revision_order_mismatch`, `revision_identity_mismatch` | Snapshot membership/number sequence differs |
| `revision_digest_mismatch` | Canonical immutable snapshot digest differs |
| `observation_missing`, `observation_extra`, `observation_order_mismatch`, `observation_identity_mismatch`, `observation_record_mismatch` | Observation sequence or values differ |
| `reference_missing`, `reference_extra`, `reference_order_mismatch`, `reference_identity_mismatch`, `reference_record_mismatch` | Reference ordinal sequence or values differ |
| `packet_replay_mismatch` | Remaining packet content or selection differs |
| `manifest_missing`, `manifest_extra`, `manifest_order_mismatch`, `manifest_identity_mismatch` | Full ordered manifest case-identity membership differs |
| `packet_digest_mismatch`, `manifest_member_mismatch`, `manifest_replay_mismatch` | Selected member digest/metadata or remaining manifest differs |

Missing/extra codes describe record-count differences. Equal counts with changed
identities use identity mismatch; equal identity multisets in a different order
use order mismatch. Exact typed serialization distinguishes `true` from `1`.

## Focused validation

```text
python -B -m unittest discover -s tests/fast8_packet_verifier -v
python -B manage.py test tests.fast8_packet_verifier.test_services tests.fast8_packet_verifier.test_cli tests.editorial_workbench.test_packets tests.editorial_export.test_services --settings=config.settings.test --noinput --verbosity=1
python -B -m ruff check --no-cache apps/fast8_packet_verifier tests/fast8_packet_verifier
python -B -m ruff format --check --no-cache apps/fast8_packet_verifier tests/fast8_packet_verifier
```

Use explicit module names for Django's runner: the root `tests` is a namespace
package, so package-label discovery is not portable in this checkout.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. No owner-source acceptance or policy changes.
