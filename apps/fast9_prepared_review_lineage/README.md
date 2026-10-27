# FAST9 prepared / review / export lineage conformance

Base: FAST8 Draft PR #151, `0769f66e93fdf710ca55e9e68e87430a93f14c40`.
PR target: `codex/20261026-fast8-integration-pc1` (not main).
Only this app and the matching `tools/` and `tests/` folders are owned.

This read-only adapter composes the actual FAST8 prepared projection, editorial
export, single-packet verifier, review export and workflow invariant replay. It
does not invent a prepared-to-stock-workflow connection or persist a review.
No HTTP/UI surface, database access, migrations, schema changes, content edits,
external network, owner archives, credentials, real identities or roles.

## Real connections and limits

1. `fast8_prepared_review.project` validates the caller's bounded source/state
   pinned attempts against existing fixed prepared fixtures. The complete result
   is retained, including rejected commands, source text, reference identities,
   exact initial/final states and every before/after snapshot and hash.
2. `editorial_export.verify_export` checks all four source members by exact
   regeneration before decoding. `fast8_packet_verifier.verify_packet` verifies
   the selected workbench packet and original manifest independently.
3. The selected prepared row joins that packet by exact case, parent batch,
   payload SHA, row ordinal, external ID, parsed-row SHA, source text, references,
   intake diagnostics and initial revision snapshots. The prepared-case SHA is
   retained from the authoritative prepared service. Parent means **input batch**;
   no parent review event is invented. Parsed row SHA hashes serialized parsed
   fields, not an original CSV byte slice. Missing source offsets stay null.
4. `fast8_review_export.verify_preview` verifies all three preview members.
   `workflow_invariants.replay` independently reproduces the selected stock
   scenario and its digest. Its case is explicitly separate from the prepared
   row. The selected prepared preview member has no review events. Exported
   snapshots are the original receipt; projected final review states are not
   silently exported or presented as saved state.

`SUPPORTED` at record level means this synthetic conformance check executed.
Per attempt it means only an accepted pure-contract projection. `REJECTED`
preserves rejected attempts; CLI input/verification failures return a minimal
rejection with no partial evidence. `NOT_CONNECTED` records missing joins,
including absent draft snapshots and persisted review. `NOT_RUN` records database
and browser work that was not performed. An overall supported record can contain
rejected attempts and missing joins; it is not end-to-end review acceptance.

All 11 existing prepared rows are selectable, including seven without a draft.
The default `batch-synthetic-csv-1` includes exact Arabic combining marks,
decomposed `e\u0301`, leading/trailing spaces and embedded CRLF. No Unicode,
newline or timestamp normalization is performed. Duplicate `SYN-SHARED` IDs in
CSV and JSON retain distinct batch/row identities. Unknown/stock keys reject.

## Commands (Python 3.13, repository root)

```powershell
python -B -m tools.fast9_prepared_review_lineage --synthetic-fixtures-only
python -B -m tools.fast9_prepared_review_lineage --synthetic-fixtures-only --case-key batch-synthetic-json-1
python -B -m tools.fast9_prepared_review_lineage --synthetic-fixtures-only --scenario blocked
python -B -m unittest discover -s tests/fast9_prepared_review_lineage -v
python -B -m ruff check --no-cache apps/fast9_prepared_review_lineage tools/fast9_prepared_review_lineage tests/fast9_prepared_review_lineage
python -B -m ruff format --check --no-cache apps/fast9_prepared_review_lineage tools/fast9_prepared_review_lineage tests/fast9_prepared_review_lineage
```

CLI writes one deterministic UTF-8 JSON record to stdout, without filesystem
output options. Exit 0 means a diagnostic record was produced, not every attempt
accepted. Exit 2 means rejection. Missing opt-in/invalid arguments use argparse's
exit 2. Production flags reject before reading files. Optional exact synthetic
bundles can be inspected without rewriting their bytes or modification times:

```powershell
python -B -m tools.fast9_prepared_review_lineage --synthetic-fixtures-only --source-bundle <existing-synthetic-export-directory> --review-bundle <existing-matching-review-preview-directory>
```

`--review-bundle` requires `--source-bundle`; omit both to generate in memory.
Supported scenarios are `rehearsal`, `preparation`, `blocked`. Reads require the
exact member inventory, regular files and bounded sizes. Symlinks and Windows
reparse points in existing path components reject. No source/archive discovery.
The command is for controlled offline fixture directories, not concurrently
mutable directories or an upload service. CLI verification failures never echo
paths, input contents or raw exceptions. Do not use PowerShell text redirection
to preserve canonical UTF-8 bytes; capture subprocess stdout as bytes instead.

## Validation

See [VALIDATION.md](VALIDATION.md) for exact commands, results and limitations.
The initial test run failed because the new module was absent; the CLI's seven
tests also failed before implementation. No tests were skipped or marked xfail.
Tests call the real services and serializers; only provider-drift tests inject
modified prepared results to exercise cross-service disagreement rejection.

PostgreSQL is **NOT_RUN**. No disposable cluster identity or trusted runner
authorization was supplied for this lane, and these contracts have no persistence
join. No credentials were inspected or connection attempted. A full default
Django suite is also NOT_RUN because it includes database/browser work outside
those prerequisites. The focused affected suite uses only unittest/SimpleTestCase
classes and does not create a database. No PostgreSQL claim follows from it.

If the coordinator supplies a separately preauthorized Wave7 disposable synthetic
cluster, the existing trusted runner remains the only opt-in route for adjacent
persisted-domain tests (not a new lineage persistence claim):

```powershell
python -B manage.py test tests.wave7_foundation.test_database tests.wave7_foundation.test_service_integration --settings=config.settings.wave7_test --noinput --verbosity=2
```

Run only with the coordinator's already-provisioned synthetic environment. That
runner validates configured/actual identity and ownership before creating its
test database or running existing migrations; it rejects preexisting test DBs.
This lane supplies no provisioning, credential lookup or bypass command.

Inherited B6/C6/D6 workflows are unchanged. Their green status does **not** prove
collection of these new FAST9 modules; their explicit FAST8 lists omit this lane.
Remote statuses and exact tested SHA belong in the PR/final handoff.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING. Source-owner, catalog, policy and
production acceptance remain NOT_CONNECTED regardless of synthetic test success.
