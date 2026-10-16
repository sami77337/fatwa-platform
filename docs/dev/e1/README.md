# Wave6 E1: exact prepared input

Development base: `codex/20261017-wave5-review-worklist` at
`b5de539237de0cd12b91b0705a3cb92014bfe98b`. E1 changes only its assigned paths.

C1 now preserves question, staff-note and media strings exactly. Arabic marks,
leading/trailing spaces, tabs, CRLF and LF survive JSON/JSONL/CSV decoding,
canonical JSON/JSONL serialization, D1 and C2 serialization. `title` remains a
legacy input alias for `question`; its text is copied exactly. Blank-field and
legacy title/question conflict checks may inspect stripped copies, but never
write those copies into the original fields. There is no derived search field
in this adapter and no Unicode normalization.

C1 accepts at most 1,000,000 input bytes, 1,000 records and 100 references per
record. The CLI reads at most the byte limit plus one sentinel. CSV and JSONL
record iteration stops at the row limit plus one; JSON parsing is first bounded
by input size. Over-limit reference lists are rejected before scanning their
contents. D1 checks canonical reference-list eligibility before calling C1.
Existing maxima themselves are accepted, including a 1,000,000-byte D1 batch
with 1,000 rows and a row containing 100 references.

Duplicate JSON keys, nonfinite constants/numeric overflow, excessive nesting,
invalid UTF-8 and escaped lone surrogates are rejected. This includes invalid
Unicode in fields/rows that would otherwise be rejected later. JSONL splits on
physical CR/LF, preserving U+2028/U+2029/U+0085 inside JSON strings. Payload
`reference_map`, `catalog`, `bridge_config` and numeric identity fields remain
untrusted unknown fields. Mapping/catalog objects are explicit caller arguments.

`prepare_batch(raw, *, synthetic_fixtures_only=False, reference_map=None,
catalog=None) -> Batch`, `Batch.report`, `Batch.drafts`, and D3 contracts remain
unchanged. D1 retains every original row and reports errors per row; all
occurrences of a duplicate external ID are blocked. Missing media remains
visible for review, with no placeholder URL and no C2 draft. Unmapped or
mismatched references stay unverified; they do not establish scholarly evidence.
The synthetic receipt is revision 1 with an empty answer, never human approval.

## Eligibility and adapter boundaries

| Input | C1 adapter | D1/C2 draft |
| --- | --- | --- |
| HTTPS, no explicit port or port 443 | Eligible | Eligible if remaining fields valid |
| HTTP, or HTTPS with port 8443/444 | Eligible HTTP(S) metadata | Blocked by existing C2 contract |
| Surrounding URL whitespace | Invalid; original URL is never repaired | Blocked |
| Missing/empty media | Review finding | Visible row, no draft |
| More than 100 references | Invalid row | Visible blocked row, no draft |

C1's existing invalid-artifact behavior is preserved: its candidate outputs
contain eligible rows only, while the manifest remains `INVALID`, identifies
the original row ordinals, and prevents CLI export. Do not treat those candidate
bytes as a successful batch or feed them to D1 while ignoring the manifest.
To retain mixed blocked rows in D1, submit the original canonical JSON envelope
to `prepare_batch`; D1 does not silently filter its report. CSV reference cells
are parsed by C1 into lists; canonical D1 requires actual JSON lists.

## Exact synthetic handoff for E2

Run from repository root using the uv venv based on `/usr/bin/python3.13`:

```sh
.venv/bin/python -m docs.dev.e1.synthetic_example
```

The executable fixture [synthetic_example.py](synthetic_example.py) returns exact
`raw, reference_map, bridge_config, catalog` from `build_inputs()`. There are no
reads of source archives, database connections, media requests or persistence.
Every identity is invented, including the internally required book `622` pin;
it is not evidence about the owner's book/catalog. Its input is 1,474 bytes,
SHA-256 `ed9f754f67fdf1c46608111a8e99065c709c9b7888a1d1eb06e9d90458bdb9e7`.
The D1 report is 7,752 bytes, SHA-256
`37fee8f8cc25730f05561f892441f87a4e9a1fcba374a5a21e9e7fd921814884`.

Every question is exactly this Python string, including its final spaces:

```python
" \tسُؤالٌ اصطناعيّ\r\nالسطرُ الثاني\n  "
```

| Ordinal / external ID | D1 primary status | Draft | Reference outcome |
| --- | --- | --- | --- |
| 1 / SYN-E1-valid | ready-for-editor | yes | verified synthetic TOC |
| 2 / SYN-E1-missing | needs-editor-review | no | absent |
| 3 / SYN-E1-invalid | blocked-invalid | no | absent |
| 4 / SYN-E1-duplicate | blocked-invalid | no | absent |
| 5 / SYN-E1-duplicate | blocked-invalid | no | absent |
| 6 / SYN-E1-unmapped | needs-editor-review | yes, no invented reference | unverified |
| 7 / SYN-E1-mismatch | ready-for-editor + references-unverified | yes | mismatched |

The unchanged D1 readiness status concerns intake, not verified evidence or
publication. E2 must continue suppressing mismatched citations. Summary:
`ready-for-editor=2`, `blocked-invalid=3`, `needs-editor-review=2`,
`references-unverified=6`; seven report rows, three drafts. The first row's
staff notes are exactly `" ملاحظةٌ\t\n "`.

Baseline D3 rejects the seven-row example with `ValueError: Duplicate
external_id`; its duplicate handling is an E3/E2 integration dependency, not an
E1 production edit. A concrete five-row compatibility variant works today:

```python
import json, runpy
raw, reference_map, bridge_config, catalog = runpy.run_path(
    "docs/dev/e1/synthetic_example.py")["build_inputs"]()
data = json.loads(raw)
data["items"] = [r for r in data["items"] if r["external_id"] != "SYN-E1-duplicate"]
unique_raw = json.dumps(data, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")).encode("utf-8")
# E2 after assembly:
# compose_synthetic_batch(unique_raw, synthetic_fixtures_only=True,
#     reference_map=reference_map, bridge_config=bridge_config, catalog=catalog)
```

D3 resolves five rows in this variant. D1 returns three drafts and summary
`ready-for-editor=2`, `blocked-invalid=1`, `needs-editor-review=2`,
`references-unverified=4`. E2 composition itself is not implemented or claimed
tested by E1. The coordinator must rerun E2/E3 suites after assembly.

No shared dependencies, routes, migrations, source fixtures or E2/E3 production
paths changed. No independent review or product/source acceptance is claimed.
NOT_DEPLOYED / GATES_HOLD; Gate B NOT_PASSED, C/D/E HOLD, Phase01 BLOCKED.
