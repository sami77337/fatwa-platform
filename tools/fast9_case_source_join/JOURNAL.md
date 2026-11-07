# Saved synthetic source history

This local development journal records the fixed Wave7 source events used by the workbench. A new process can reopen the same file. The Django database configuration and Wave7 PostgreSQL tables are separate from this store.

## Run the operator demo

Use the project’s Python 3.13 environment. Create an empty, private, local directory and set `FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR` to its absolute path in the shells running the CLI and the development server. The directory must support SQLite locking and hard links. The journal always uses the same filename in that directory.

```sh
python -m tools.fast9_case_source_join.journal --synthetic-fixtures-only --case-key intake-7 show
python -m tools.fast9_case_source_join.journal --synthetic-fixtures-only --case-key intake-7 record received
python -m tools.fast9_case_source_join.journal --synthetic-fixtures-only --case-key intake-7 record corrected
python -m apps.editorial_followup
```

Open the case at <http://127.0.0.1:8016/dev/editorial-workbench/intake-7> and follow the saved journal link. Stop and restart the development server with the same directory to inspect the saved correction again. The four original example links remain separate scenarios. GET and HEAD read the selected case’s committed history.

Each `record` command submits one pre-defined event only. The `deleted` and `restored` samples are alternative successors to the same `corrected` example. An exact retry is idempotent. A missing or stale predecessor is refused. The CLI supports all three fixed fixture cases; the saved-draft screen applies only to intake-7, which has a matching receipt-stage draft.

## Verify a restore against an earlier receipt

The `checkpoint` in a successful write or nonempty `show` output contains the count and SHA-256 digest of that case's canonical event chain. Keep a trusted copy outside the journal and its backups. After restoration, supply the values from that receipt as positional arguments to `verify`.

```sh
python -m tools.fast9_case_source_join.journal --synthetic-fixtures-only --case-key intake-7 verify COUNT SHA256
```

Success confirms the saved prefix and allows further events after it. A shorter history or a different event at that prefix returns a nonzero exit. This is an integrity comparison; the receipt is unsigned. The unpinned reader cannot detect replacement with an entire older, internally consistent copy, or prove that a provider supplied all events. Nothing here records human acknowledgment or authorizes publication or delivery. See the [journal contract](../../apps/fast9_case_source_join/README.md) for the trust boundary.
