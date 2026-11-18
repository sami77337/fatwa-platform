# V14 — source correction and pending 556-point trace

**Gate B NOT_PASSED · C/D/E HOLD · Phase01 BLOCKED · NOT_DEPLOYED.**
The leadership reference is 83% ±9; no new estimate or acceptance is assigned.
This folder is an isolated documentary extension above V13 at
`1f08cbb7166f70ec340c495da33ccfc1eda9534e`.

The [source-lineage correction](SOURCE_LINEAGE.md) commits the parent-local DOCX,
registry and text receipt that previously changed only PR #232's description.
DOCX is locally verified by the parent; no independent Cloud byte inspection is
claimed. Historical workbook transformation and authorship remain unproved.
The historical V12/V13 files and their evidence are unchanged.

`matrix.json` preserves every field of all 556 V13 rows and appends only `v14`.
That includes the original texts, SPEC IDs, decisions, locators, historic source
status field names and all old evidence SHAs. The current lineage status belongs
to the attributed V14 extension, not a retrospective alteration of those fields.
The preserved classifications are **303 PARTIAL, 52 DECISION,
168 NOT_IMPLEMENTED by then-available evidence, 33 OUT_OF_SCOPE, 0 COMPLETE**.
These are documentary classifications, not a new progress percentage.

**V14 runtime evidence is PENDING.** The scaffold credits zero V14 points.
It does not describe new functions as tested, a subset as a complete journey,
existing V13 checks as new V14 execution, or historical startup failures as fixed.
A later reviewed update must bind selected point/SPEC IDs, files and symbols,
exact product SHA, positive and negative executed tests, separate PG17/18 receipts,
Chrome sandbox evidence for affected UI, current independent security review,
and remaining gaps. Merely adding a green workflow or SHA is rejected.

## Integration contract

Ownership: this new folder only. No app, migration, service or routing change.
The integrator may cherry-pick the supplied commit. No source binary is included.
The generator reads pinned git objects, so the V13 base must be present in checkout.
It needs only Python's standard library and git; no PostgreSQL or product rerun.

```sh
python3 docs/product/v14_scope_evidence/build.py --check
python3 -m unittest discover -s docs/product/v14_scope_evidence -p 'test_*.py' -v
```

Without `--check`, the generator writes four derivatives here: `matrix.json`,
`matrix.csv`, `MATRIX.md` and `summary.json`. Baseline hashes detect changed input;
negative tests reject attribution inflation, workbook conflation, lost UTC
serialization differences, unreviewed runtime credit and status/percentage upgrades.
The current strict `validate_evidence` intentionally accepts only the pending
scaffold. Replace it with a reviewed exact-execution contract when actual V14
receipts are supplied; do not disable it to insert unsupported evidence.

[Readable matrix](MATRIX.md) · [CSV](matrix.csv) · [source receipt](source_lineage.json).
