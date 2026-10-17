# Wave7 E3 reference verification

Foundation/base: `34355f5173667c6167351cf379ad56957d7f35f3` on
`codex/20261017-wave7-e5-foundation`. This dispatch supplies independent foundation
acceptance; this producer does not claim to have performed that review. The older
pending wording in foundation documents is superseded by the dispatch. No PR58
metadata was changed. Lane branch `codex/20261017-wave7-e3`, isolated worktree
`/workspace/fatwa-wave7-e3`; previous Wave6 E3 worktree/head preserved.

## Public service and E1/E4 contract

```python
verify_batch_references(
    batch_id: UUID, *, synthetic_fixtures_only: bool = False, using: str = 'default',
) -> BatchReferenceVerification

plan_reference_verification(
    raw: bytes, *, synthetic_fixtures_only: bool = False,
    catalog_rows: tuple[Heading, ...] = (),
) -> tuple[ItemReferenceVerification, ...]
```

Both live in `apps.intake_workflow.references`. The write service accepts a UUID,
not an opaque string to coerce. It has no caller/payload source-map/catalog option.
The pure planner accepts asserted immutable Heading snapshots for pure validation;
empty evidence produces UNVERIFIED references and never opens a DB.

Returned frozen DTOs:

- `BatchReferenceVerification(batch_id, payload_sha256, items)`.
- `ItemReferenceVerification(row_ordinal, source: SourceSlice, references)`.
- `ReferenceVerification(reference_ordinal, source: SourceSlice, status, reasons,
  identity=(), evidence=None, citation_text='')`. `identity` is an immutable tuple
  of field/value pairs. `derived_values()` returns a fresh JSON-safe dictionary
  containing exactly `reference_status`, `verification_results`,
  `verified_identity`, `citation_text`.

E1 must commit its intake `synthetic_atomic` unit before invoking E3. E3 opens
its own sole guarded unit, with the guard before transaction/model access. Do not
wrap this service in another application transaction. This separation means a
verification error does not imply the already committed intake was rolled back;
report the verification error separately and retain the UNVERIFIED intake records.
There is no implicit call from a GET view. Only explicit authorized service/CLI
callers may request these synthetic derived updates.

E1 persists **every** item and array reference token, including scalar/null/invalid
rows/pointers, with exact `SourceSlice.text/start/end`. Non-array reference_links
has zero reference tokens. Ordinals, not external IDs, associate persisted records.
E3 rejects incomplete persisted item/reference collections; it never invents their
missing originals. Initial reference state is UNVERIFIED with empty identity and
citation. Duplicate external IDs/blocked intake rows can still have independently
verified references; this never changes intake readiness or implies approval.

E4 reads persisted derived fields; verification does not introduce HTTP writes.
`citation_text` uses the existing escaped D3 citation renderer, without safe marking.
It describes a TOC heading, not a scholarly ruling. No source/edition selector,
answer, review event or permission path is added.

## Trust, current catalog and immutable provenance

All raw parsing uses accepted `parse_synthetic_payload`, never default float JSON
decoding or source serialization. Complete original reference token text and
absolute UTF-8 byte slices are included in derived provenance, together with their
SHA256. Source records/text/offsets and the batch bytes/hash are checked against a
fresh parse of `original_payload` before any derived update. Nothing trims source
strings, rounds decimals, stringifies numeric IDs or changes lexical number tokens.

Trusted maps come only from fixed foundation fixtures and must agree completely
with `SOURCE_IDENTITY`/`VERIFIED_IDENTITIES`, including explicit numeric bindings.
C1 requires exactly source_id/heading_id; C2 requires all six textual identity
fields. Missing/malformed/unknown pointers stay UNVERIFIED; conflicting complete
C2/source/config/catalog evidence is MISMATCHED. Exact duplicate textual pointers
within an item stay UNVERIFIED at their distinct original source ranges. No mapping
is inferred from question text, numeric-looking strings or equal heading titles.

The write service locks batch, ordered items, ordered references, then reads each
required explicit current catalog row once (maximum three fixed targets). It checks
work/source/edition/input/archive metadata, complete printed location and full
root-to-target titles. A second bounded projection checks actual target source_id,
parent source-row/edition/source_id and depth. This prevents a different ancestor
with the same title from passing a full-path title comparison. All expected facts
are the fixed fabricated catalog in the accepted foundation seed; changing that
fixture requires coordinated updates to this explicit allowlist.

Legacy Heading constructors with optional edition/archive fields set to None are
compatible only when complete fixed D1/D3 bindings exist and all remaining metadata
matches. Explicit conflicts never pass. Pure snapshots and stored pins are caller
assertions, not independent archive inspection; persisted service reads actual DB
evidence, and `archive_inspected` remains false in results.

Only the four derived reference fields change. Source originals/offsets, item
intake/review states, batch fields and events remain untouched. Identical reruns
perform no UPDATEs. A real DB read/write error aborts the unit; a failed call must
not be represented as current successful verification. There is no retry with a
weaker guard or optional PASS fallback. Earlier stored results remain the previous
snapshot if an entire failing unit rolls back; no new result is returned.

## Actual local evidence

Existing ready Cloud executor, environment ID
`ccarenv_b64_Y2NhcmVudl9jZWIwOGY2ODQ0OTQ4MTkxOGVhNTRhNTcyYjM2MjQ5Mw`.
New task URL/ID NONE exposed; one executor/quota not otherwise observed. Debian
13.6, `/usr/bin/python3.13` 3.13.5, Node24.19.0, Docker28.4.0. Reused the isolated
`/tmp/e3-venv` created by `uv venv --python /usr/bin/python3.13`; `uv pip list`
confirmed the same eight exact PyPI pins in unchanged requirements.txt. No new
dependency, credential, permission, decimal/integer limit or security setting.

Deterministic RED/GREEN:

1. Initial 12-method feature suite: 26 missing-module error/subtest events.
2. 15-method run: one guard-order error, models loaded before disabled-write
   rejection. Guard now precedes model loading.
3. PG18 replay probe found unnecessary repeated UPDATEs because tuple path data
   became lists after JSON storage. A 16-method pure run reproduced one failure;
   derived JSON path lists now compare identically on replay. Source data was never
   converted or rewritten.
4. An actual separate owned PG17 negative catalog had a different parent row (99)
   with the exact same title as allowed root row 1. Before the projection fix the
   stored result was VERIFIED (assertion RED); after the fix the same retained
   records became MISMATCHED/empty identity/citation. Added pure projection regression.

Final commands (`PY=/tmp/e3-venv/bin/python`), counts and limits:

| Command | Actual result |
| --- | --- |
| `PGPORT=1 $PY -m unittest discover -s tests/reference_links -v` | 67 PASS = 50 retained + 17 new; 0 FAIL/ERROR/SKIP |
| `PGPORT=1 $PY -m unittest tests.wave7_foundation.test_contracts tests.wave7_foundation.test_guard_config tests.wave7_foundation.test_lossless -v` | 25 PASS, 0 FAIL/ERROR/SKIP; exact-million-byte integer regression included |
| `$PY tools/dev/wave3_qa.py --standalone --require-integrated` | PASS; intake30 + drafts17 + refs67 + full importer84 = 198 executions, 194 PASS/4 source-asset SKIP |
| `$PY tools/dev/wave4_qa.py --wave3 --json /tmp/w7-e3-d6-summary.json` | PASS; D1 41, D2 61, D3 67, D4 Django12/Node49, D5 18, nested C6 198 = 446 executions including repeated suites; 442 PASS/4 source-asset SKIP |
| `$PY /tmp/w7-e3-database-probe.py` with the explicit synthetic environment below | 9 scenario groups PASS on PG18.6 and 9 PASS on PG17.11; these are temporary probes, not committed test-case counts |
| `$PY /tmp/w7-e3-path-probe.py` on the separate owned negative PG17 database | 1 additional actual ancestor-identity scenario PASS after observed RED |

The temporary probes exercise actual migrations 0001..0004 and guarded writes:
three fixed references across eight retained rows; immutable originals and item
readiness/events; replay with zero UPDATEs (17 total SQL statements including guard
and transaction); C2 conflict/missing/scalar cases; exact fractional/underflow/huge
exponent/6000-digit integer/null storage; stale path evidence downgrade; actual
catalog-table read failure with rollback; failure after the first real derived
UPDATE with complete rollback; incomplete item/reference collections; rejection
inside an existing outer transaction. The negative ancestor fixture was inserted
only in a separate empty, explicitly claimed synthetic DB; no existing catalog
row or trigger was repaired/disabled.

Explicit environment: FATWA_WAVE7_SYNTHETIC_WRITES=1, FATWA_PRODUCTION=0,
PGHOST=127.0.0.1, PGUSER=wave7_synthetic, synthetic disposable password,
DJANGO_SETTINGS_MODULE=config.settings.wave7_development,
PYTHONPATH=/workspace/fatwa-wave7-e3. Actual server identity and immutable ownership
marker verified before migrations/seed. Containers/databases are this producer's:

- `wave7-e3-pg18`, port56483, base `wave7_synthetic_e3_pg18`,
  test name `test_wave7_synthetic_e3_pg18`, PG18.6.
- `wave7-e3-pg17`, port56473, base `wave7_synthetic_e3_pg17`,
  test name `test_wave7_synthetic_e3_pg17`, PG17.11.
- Separate known-created negative DB on PG17: `wave7_synthetic_e3_path17`,
  configured test name `test_wave7_synthetic_e3_path17`.

Probes explicitly initialize the empty ownership marker before migrate and seed
outside any other transaction. Known nonempty owned data was retained on reruns,
never reset. Long raw logs/scripts are ephemeral under `/tmp/w7-e3-*` and are not
owner-data artifacts. No permanent DB test module was added: see
[DB_TEST_PROPOSAL.md](DB_TEST_PROPOSAL.md) for the root/E5 integration proposal.

No shared model/migration/contract/fixture/guard/settings/route/CI file changed.
E5/root must add a separately assigned actual DB label after assembly; never feed
it to port-1 pure discovery. Combined E1/E3 persistence, full Wave7 commands/browser,
independent review and source/product acceptance remain NOT_RUN here. Exact final
head, postcommit checks and CI observations are in the Draft PR/handoff.

C6/D6 importer skips are expected missing real owner assets, not substituted
synthetic source acceptance. Full importer is discovered (84 cases, 80 PASS,
4 skips); the skip report names each absent owner ZIP/source check. No owner
archive was obtained or imported. Precommit wrapper runs name the foundation SHA
and DIRTY tree while authoring; postcommit reruns bind the final code to a clean SHA.

NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED.
