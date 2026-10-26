# Synthetic failed-batch recovery preview

This adapter makes the existing `prepared_pipeline.diagnose_batches` evidence
available through an offline, fixed-identifier recovery command. It reuses
`apps.editorial_workbench.batch_fixtures.synthetic_inputs()` without adding a
fixture corpus or accepting paths, uploaded bytes, source inventories or mappings.
It performs no persistence, correction or resubmission. There are no HTTP routes,
database dependencies, migrations or network calls.

From the repository root, using the existing Python 3.13 environment:

```powershell
python -B -m tools.fast8_intake_recovery --failed-only
python -B -m tools.fast8_intake_recovery --batch synthetic-csv --row 2 --json
python -B -m tools.fast8_intake_recovery --batch synthetic-malformed --json
python -B -m tools.fast8_intake_recovery --batch synthetic-jsonl --row 1
```

`--batch` accepts only `synthetic-csv`, `synthetic-json`, `synthetic-jsonl` and
`synthetic-malformed`. Omit it to view the collection. `--row` requires a batch
and uses the original one-based **record ordinal**, not a physical line number.
It cannot be combined with `--failed-only`. Invalid selectors exit 2 before any
output; a nonexistent or unparseable row is never synthesized. JSON is written
as UTF-8 bytes, independently of Windows console encoding.

Exit 1 means the selection contains blocked rows or an unparseable batch.
Exit 0 means no such failures in the selection; it does **not** mean accepted,
corrected, verified or published. Every row still requires manual review.
`accepted_record_count` is always zero. The upstream preparation statuses are
retained explicitly as `upstream_statuses`, without exporting their in-memory
drafts as recovery results. No recovery action invokes submission.

The complete fixed collection is diagnosed before selecting rows. For example,
CSV row 2 remains `BLOCKED_INVALID` and links to JSON row 1 in its duplicate
group, even when only the CSV row is requested. `--failed-only` yields the six
rejected original ordinals and the malformed batch; it never renumbers them.
Collection counts and selected counts are separate. Batch failures retain
`MALFORMED_INPUT`, full input bytes and digest, with `row: null`; upstream does
not provide per-row parse codes for files it cannot parse, so none are inferred.

JSON includes the selected batches' original `raw_base64`, SHA256, row byte
offsets (zero-based, exclusive end), row IDs, original parsed values, CSV extra
cells, findings and unchanged diagnostic recommendations. Recommendations retain
their code, field, severity, reference position and existing Arabic recovery
text. CRLF, quoting, combining marks, source IDs and raw bytes remain untouched.
Some unchanged upstream advice mentions diagnostic-tool flags such as
`--source-id`; those flags are deliberately unavailable in this fixed preview.
Parsed values are not a replacement for the authoritative raw byte receipt.
`collection_inputs` pins the full diagnostic context, including other batches
referenced by duplicate locations. There is no invented inventory or source join:
source inventory is `NOT_SUPPLIED`, reference mapping is `NOT_CONNECTED`.

## Fixture identity

Base: `92fa517ecdefe3f1a92a1ab145ff55943474df44`, Draft PR #134. These are
existing fabricated in-memory fixtures, **not user-owned source archives**.

| Batch | Bytes | SHA256 |
| --- | ---: | --- |
| synthetic-csv | 719 | `0e5d1bfe94c5f9abf5652a065b57212fcaa143abd738f95f2b233df5b68410f8` |
| synthetic-json | 620 | `d96eaabe7207a71ccdc1bc0426bf486f8448651ec34bf59e3ae96599b71c5aec` |
| synthetic-jsonl | 714 | `e8caaf496a756df9a7867f6a8ff9f4b9074d85eb0374f51d5e4c742803456363` |
| synthetic-malformed | 13 | `d4360bc841807dbc8d40aa57d52210c8b12413a8940b57310a8b3d14d1ca7086` |

There are 11 parsed rows, six blocked rows and one unparseable batch. Tests pin
these identities and compare every row's evidence to actual upstream diagnostics.
Adversarial test bytes are explicitly fabricated in memory and reach the private
projection helper; they are not an alternative public input interface.

## Focused verification

```powershell
python -B -m unittest discover -s tests/fast8_intake_recovery -v
python -B -m ruff check apps/fast8_intake_recovery tests/fast8_intake_recovery tools/fast8_intake_recovery
python -B -m ruff format --check apps/fast8_intake_recovery tests/fast8_intake_recovery tools/fast8_intake_recovery
```

Shared CI is unchanged and does not explicitly register this new lane. Its B6,
C6 and D6 results must be reported separately from the local focused tests;
green inherited CI alone does not prove this adapter's acceptance. No browser
surface was introduced. PostgreSQL and owner-source acceptance are `NOT_RUN`.

Local verification on Python 3.13.15: 15 new tests passed, zero skips; four
directly used upstream diagnostic tests passed, zero skips (all-format byte
provenance, cross-batch duplicates, malformed input isolation and unknown versus
empty inventory). Ruff lint and formatting passed. Initial lint caught one
unused test import, which was removed. One independent final review completed
with no findings and independently confirmed the same 15 tests; these are not
counted twice. Remote SHA and actual CI results belong in the Draft PR evidence.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING. No scholarly answers, publishing,
role grants or owner approvals are enabled or inferred.
