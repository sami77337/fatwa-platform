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

## Record reading a specific version

From an interactive project terminal run the following command and open <http://127.0.0.1:8017/review/>. The launcher displays a temporary reviewer token. Sign in with the token, read the question, and record the reading. The reviewer session lasts 30 minutes. The desk flags later corrections or deletions and links to the first event after the saved reading. A form opened before a correction returns HTTP 409 with the updated text; review it before submitting again.

```sh
python -m apps.editorial_workbench.reviewer_server --demo
```

The first demo launch creates a persistent journal in `.local/reviewer-desk` and records one synthetic intake. To try a correction, point the event CLI in another terminal at the absolute path of that directory and run `record corrected` as described above. To open a dedicated existing journal, set `FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR` and omit `--demo`. All processes sharing that journal must use this version once the first reading has been recorded. That write adds the v2 receipt table in the same SQLite transaction; the older journal tool only understands v1.

A preconfigured launcher can use `FATWA_SYNTHETIC_REVIEWER_TOKEN_SHA256`, the lowercase SHA-256 of the ASCII representation of a random 64-character lowercase hexadecimal token. It authenticates a single training reviewer. Each receipt identifies the draft fingerprint and the committed source prefix. The original development app stays read-only. A reading receipt does not grant scholarly approval.

After recording a reading, the desk can save a typed training clarification for the same case. The case waits for a reply. An operator can simulate its arrival by entering invented text or selecting an example. The original question and conversation are kept separately. A new reply is marked unread even when the source wording is identical. Read the reply before recording a fresh receipt or asking another question. Both desks show the saved thread and its associated source version.

The first successful clarification upgrades the dedicated local journal to v3. Use the same code version for all processes that share it. HTTP remains limited to the training workstation; these actions do not contact a requester.

## Answer from the local requester page

After saving a clarification, choose **إصدار رمز الردّ** in the reviewer desk. Open **صفحة صاحب السؤال** in a separate browser profile on the same machine and enter the issued code. The requester can read that specific prompt, submit one training response and keep the displayed reply reference. The desk shows the same reference and identifies the reply as coming from the requester page.

The code expires after 30 minutes. Replacing or cancelling it, changing the source, or saving an answer closes the old code. The first issue upgrades this local journal to v4. Use this version in all processes that share it. The independent workbench preview is for a trusted development workstation; the reviewer and requester demonstration runs on the dedicated loopback desk.
