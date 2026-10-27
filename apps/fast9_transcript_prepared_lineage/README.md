# FAST9 transcript-origin prepared lineage

Development-only, read-only composition of the actual `fast8_transcript_queue`,
`fast8_segment_timeline` and `prepared_pipeline` services. Previously the transcript
queue allowed unanswered questions and its question-only preparation export had no
joined manual timing receipt. This bridge requires a complete manually supplied
synthetic Q/A pair and exact retained file/source pins before emitting any artifact.

Base: FAST8 Draft PR #151, `0769f66e93fdf710ca55e9e68e87430a93f14c40`.
Lane: `codex/20261027-fast9-transcript-prepared-lineage-pc1`.
Draft PR target: `codex/20261026-fast8-integration-pc1` (not main).
The tested lane commit is recorded in the PR; obtain it locally with `git rev-parse HEAD`.

## Behavior and integrity

- Requires explicit synthetic attestation, an exact raw input SHA256 and the complete
  source ID -> source revision SHA256 map. The CLI requires a separate pins manifest.
- Invokes the real queue, diagnoses its same raw input through the timeline service,
  and replays the queue's unchanged preparation payload through `prepare_batch`.
- Joins exact source revision, pair and segment IDs. Shared pair/segment IDs in two
  different sources remain distinct. Every cue must join exactly once.
- Each EPHEMERAL receipt contains the actual prepared item, its canonical SHA256,
  exact Q/A evidence, segment SHA256, exact UTF-8 text SHA256, and manual cutter cues.
  Cue numeric milliseconds and formatted clocks must both match the supplied spans.
  Stage payload/report hashes make the full byte lineage inspectable.
- Fails closed for missing answers, overlap, ambiguous pairs, duplicate segment IDs,
  incomplete/stale source pins, byte tampering, CRLF changes and stage contract drift.
  Replay verification recomputes from original pinned bytes and requires the retained
  receipt report to match byte-for-byte. No supplied report can authorize a join.
- Keeps real upstream gap/input-order findings. A gap is not filled; timestamps are
  never inferred. Answers remain `SOURCE_EVIDENCE_ONLY`; prepared export is still
  question-only, with empty media/reference fields and **zero drafts**.
- Uses no fixed 20-case workbench selection, Django setup, DB, network or media I/O.
  No HTTP endpoints, URL mounts, migrations, schema changes or external AI calls.

Raw input SHA covers the entire file, including physical CRLF and JSON formatting.
Source/segment SHA follows the existing canonical upstream serialization, not a raw
file slice or recording hash. Text SHA covers exact decoded text encoded as UTF-8,
without Unicode normalization or whitespace trimming. Both file and source pins
are required because formatting-only changes need not change canonical source SHA.

Pins must be independently retained from the manually reviewed synthetic input.
Replacing both a fixture and all its expected hashes is a new input, not proof of
authenticity. Synthetic attestation is a caller obligation, not a private-data
detector. No signing, durable storage, scholarly acceptance or owner approval exists.

## Executable CLI

Run from the repository root with Python 3.13 and existing pinned dependencies.
No extra dependencies or environment variables are needed. The guard is off by
default. This is also the runnable opt-in acceptance command for the static fixture:

```text
python -B -m tools.fast9_transcript_prepared_lineage tests/fast9_transcript_prepared_lineage/fixtures/manual-qa.json --pins tests/fast9_transcript_prepared_lineage/fixtures/manual-qa.pins.json --synthetic-fixtures-only
```

Use `--export prepared`, `--export cues`, or `--export cue-csv` for the corresponding
unchanged upstream artifact. All exports first validate the complete bridge.
The default export is the lineage report. Add `--verify-receipt path/to/receipt.json`
to recompute and verify a previously retained report before exporting.

The CLI reads bounded local regular files in binary mode, rejects known symlinks,
junctions, URLs, UNC/device paths and parent traversal, and emits UTF-8 bytes only
after validation. Exit 0 is success; 1 is validation/read failure; 2 is missing
attestation or invalid arguments. Failure stdout is empty and stderr uses a fixed
message without input text or paths. The reader is not a filesystem sandbox against
concurrent local path swaps. Input/pins limit: 1,000,000 bytes; report verification
limit: 32,000,000 bytes because the report repeats bounded stage evidence.

When retaining output, use subprocess byte capture and `Path.write_bytes()`; text
shell redirection can transcode UTF-8 or alter line endings. The CLI itself never
writes output files or modifies its inputs.

## Fixture and executed validation (2026-10-27)

Fixture: `tests/fast9_transcript_prepared_lineage/fixtures/manual-qa.json`.
Four fabricated spans, two sources, reused pair/segment IDs across sources,
Arabic diacritics, leading/trailing spaces, embedded CRLF and Unicode U+2028.
No real recording, case, identity, credential or owner archive is involved.

Exact fixture SHA256:
`684f14643df41a4e155b651763b710ab98c2aace35d01a7fce2e9120d5ad415b`.

Retained source SHA256 values:

| Source ID | SHA256 |
| --- | --- |
| `fabricated-source-b` | `f3d30dd8085820ad3235744a5bbc6e1978b393cd573f687639e286a75b89b2e8` |
| `مصدر-مختلق-٩` | `6c18f4bcb51366afd60159676fec874596d417f577c2858f378c0662a7e419cb` |

The checked-in JSON has no physical line break; text CRLF remains escaped in JSON
and exact after decoding. This prevents inherited Git autocrlf settings from
changing the pinned fixture on Linux. Tests separately generate physical CRLF JSON,
JSONL and CSV bytes, verify successful preparation, then reject CRLF -> LF drift.
Raw and Git-filtered fixture blobs both equal
`9492db0ced804a1a1329a77a64742ba44c2e53ab`.

```text
python -B -m unittest discover -s tests/fast9_transcript_prepared_lineage -v
```

Result: **26 tests passed, zero skipped**, Python 3.13.15 on Windows.
Includes real CLI subprocess execution for all exports and retained report replay;
CLI runs with deliberately invalid Django settings to demonstrate no setup/DB need.
Negative stage-drift tests modify otherwise real service outputs; positive acceptance
uses the actual three services without substituted domain implementations.

```text
python -B -m unittest tests.fast8_transcript_queue.test_services tests.fast8_transcript_queue.test_contracts tests.fast8_transcript_queue.test_cli tests.fast8_segment_timeline.test_service tests.fast8_segment_timeline.test_cli tests.prepared_pipeline.test_pipeline tests.prepared_pipeline.test_batches tests.prepared_pipeline.test_diagnostics tests.prepared_pipeline.test_file_flow tests.prepared_pipeline.test_source_pins tests.prepared_pipeline.test_wave6_contract -q
```

Result: **134 collected, 133 passed, 1 existing skip**, zero failures.
The unmodified upstream `test_symlink_leaf_and_parent_are_rejected` reported
`OS does not permit unprivileged symlinks: 22`. The existing Windows junction test
did execute. No skip/xfail was added or assertion weakened in this lane.

```text
python -m ruff check apps/fast9_transcript_prepared_lineage tools/fast9_transcript_prepared_lineage tests/fast9_transcript_prepared_lineage
python -m ruff format --check apps/fast9_transcript_prepared_lineage tools/fast9_transcript_prepared_lineage tests/fast9_transcript_prepared_lineage
git diff --check
```

All passed. One independent read-only subagent reviewed final implementation/tests,
independently ran all 26 new tests with zero skips, and found no remaining blocking
issues. Its two findings (formatted cue-clock drift and Git CRLF fixture conversion)
were fixed and verified. No test command failed during final validation.

Local PostgreSQL: **NOT_RUN**; no PG service is called by this pure bridge and no
preauthorized disposable identity was supplied. No credentials were discovered and
no migrations ran. Browser: **NOT_RUN**, no UI was added. This CLI is the guarded
offline acceptance path; it is not a PG persistence runner.

B6/C6/D6 remote CI is checked on the pushed lane SHA and reported in the Draft PR.
Existing shared workflow selectors do **not** collect this new FAST9 package.
Inherited green CI must not be presented as execution of these 26 new tests.
Coordinator integration must explicitly add the test command above to shared CI.

## Governance and missing connections

Media, fixed stock cases, catalog, policy, source owner and production remain
`NOT_CONNECTED`. Synthetic technical success is not source/catalog/policy acceptance.
Official state remains: **Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING**.
No merge or deployment is authorized by this receipt.
