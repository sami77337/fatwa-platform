# FAST8 source receipt preflight

Development-only, offline verification of an **explicitly locally fabricated
receipt**. This fills the receipt-envelope gap above `apps.source_readiness`;
the existing `parse_manifest` owns source identity, digest and catalog count
validation. Its bounded `read_local` is reused for the one explicit receipt
file. No owner importer, ORM, HTTP route, migration, download, archive reader,
directory scan or private-source access is connected.

`RECEIPT_VERIFIED` means the receipt's exact bytes match the independently supplied
caller pin and its declarations satisfy this contract. It does **not** verify
that an archive exists, that its size/hash is correct, or that headings have the
claimed count/order. Those operations stay `NOT_RUN`, source/owner bytes stay
`NOT_SUPPLIED`, and catalog connection stays `NOT_CONNECTED`. A caller who changes
both the receipt and the trusted pin can approve different declarations; the pin
is not an owner signature or authorization. Never calculate a fresh pin from an
untrusted received file and call that tamper detection.

## Contract

UTF-8 JSON, at most 64 KiB, no BOM, duplicate keys, unknown fields, nonfinite
numbers or coercions. Exact bytes (including Arabic, timestamps and CRLF) are
hashed before parsing and never rewritten.

Top-level fields:

| Field | Required value |
| --- | --- |
| `schema` | `fatwa.synthetic-source-receipt.v1` |
| `fabrication` | `EXPLICIT_LOCAL_SYNTHETIC` |
| `receipt_id` | `synthetic-` followed by 1–100 lowercase ASCII letters/digits/hyphens; first character after prefix alphanumeric |
| `base_sha` | Exact externally expected 40-character lowercase Git SHA; default reviewed FAST7 base `92fa517ecdefe3f1a92a1ab145ff55943474df44` |
| `issued_at`, `expires_at` | Exact UTC `YYYY-MM-DDTHH:MM:SSZ`; validity greater than zero and at most seven days |
| `sources` | 1–32 entries below, bounded by the total receipt limit |

Freshness uses an explicit caller `as_of`, never the process clock:
`issued_at <= as_of < expires_at`. A reproducible historical check is not a claim
that the receipt is fresh today. The seven-day ceiling is this synthetic receipt
format's bound, not a product policy or owner acceptance rule.

Each source has exactly these fields:

| Field | Required value |
| --- | --- |
| `archive_id` | Synthetic identifier, same syntax as receipt ID |
| `archive_name` | Logical `synthetic-` basename ending `.zip`; Arabic is supported |
| `archive_size_bytes`, `input_size_bytes` | Declared positive integers up to `2**63 - 1`; booleans rejected |
| `manifest` | Complete existing `fatwa.source-readiness.manifest.v1`, `source_kind=synthetic`, synthetic dataset/edition IDs and input basename |
| `ordering_claim` | Exactly `kind=source_order_unique_ascending`, integer `heading_count` equal to nested `spec.expected_rows`, and `input_sha256` equal to nested `spec.source_input_sha256` |

The nested manifest carries the edition ID, source namespace/book ID, archive and
input SHA256, heading/root/depth counts, logical input name, and catalog checksum.
Counts must permit the claimed roots/depth. Ordering is only an input-digest-bound
declaration; no heading rows are supplied or reconstructed. Archive names, IDs,
digests, edition keys/IDs and dataset IDs cannot alias across entries. Casefold
and NFC comparisons detect ambiguous names without changing stored text.
Paths, drives, UNC, ADS, reserved devices, percent escapes, controls, format
characters, trailing dots/spaces and glob characters are rejected. No entry
value is ever used as a filesystem path.

## Run

Python 3.13 with existing repository dependencies. The only file option is
`--receipt`; `--archive`, `--input` and `--pinned-owner` are unsupported.

```text
python -B -m tools.fast8_source_preflight --receipt <local-synthetic-receipt.json> --expected-sha256 <independently-pinned-sha256> --as-of 2026-10-26T12:00:00Z
python -B -m tools.fast8_source_preflight
```

Optional `--expected-revision` supplies an explicit trusted revision for later
integration. It is not inferred from the receipt or from another lane's branch.
Output is one deterministic JSON object with ASCII escaping (lossless Arabic on
Windows terminals); fixed diagnostics do not echo local file paths or input text.
Exit codes: `0 RECEIPT_VERIFIED`, `1 FAIL`, `2 BLOCKED` (missing pin/time, unreadable
local receipt or invalid invocation), `3 NOT_RUN` (no receipt). No source-level
PASS or owner acceptance is emitted, including on exit 0.

## Executable synthetic example and QA

`tests.fast8_source_preflight.fixtures.fixture()` returns the exact receipt bytes
and digest in memory. It uses the existing generated two-heading readiness
fixture, never an owner archive. Fixture identity: `synthetic-receipt-v1`,
`synthetic-archive-v1`, dataset `synthetic-receipt-readiness-v1`, edition 7001;
1,727 bytes, SHA256
`1a6041cebf977ecf1f8444c48087066c4c3a8fe299f7c24457a6e959a202e0c3`.
The fixture is fixed to the explicit example date; tests do not consult today.

```text
python -B -m unittest tests.fast8_source_preflight.test_service tests.fast8_source_preflight.test_cli
python -B -m unittest tests.source_readiness.test_service tests.source_readiness.test_cli
```

The end-to-end subprocess test writes only a fabricated receipt into a temporary
directory with **no archives present**, verifies it, alters its bytes to produce
FAIL, then removes it to produce BLOCKED. Pure tests cover missing trust anchors,
stale/future receipts/revisions, duplicate identities/JSON keys, Unicode/CRLF
tampering, malformed ordering/count claims and unsafe names. The directly reused
readiness suites exercise their existing bounded-reader and provenance contracts.

No UI/browser change and no database connection. Shared B6/C6/D6 workflow files
remain unchanged; they exercise inherited integration, not automatically these
new test modules. The coordinator must register these focused modules when
integrating; a green inherited workflow alone is not new-lane test evidence.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING. No migration/rollback of data is
needed; removal of this isolated adapter reverts the development feature.
