# FAST8 synthetic ingestion boundary QA

This lane exercises the existing `content_intake`, `prepared_pipeline`, and
`transcript_pipeline` APIs and CLIs. It implements no importer, normalization,
source repair, HTTP endpoint, database write, or scholarly content. Every record
is fabricated in `fixtures.py`; URLs use `example.invalid` and are never fetched.

From the repository root, using the existing Python 3.13 installation:

```powershell
python -B -m tools.fast8_ingest_adversarial
python -m ruff check --no-force-exclude tests/fast8_ingest_adversarial tools/fast8_ingest_adversarial
python -m ruff format --check --no-force-exclude tests/fast8_ingest_adversarial tools/fast8_ingest_adversarial
```

The runner executes only this lane. JSON evidence goes to stdout; unittest output
goes to stderr. A failure or empty collection exits 1. The evidence includes the
actual checkout SHA, owned dirty status, hashes of the executed Python files,
six deterministic fixture seed identities/hashes, test-method counts and failing
IDs. Format/mutation subtests are not inflated into separate test-method counts.
Temporary fixture and bundle writes are contained in this lane's test directory
and removed by `TemporaryDirectory`. No installation is required.

| Boundary | Executable evidence |
| --- | --- |
| CSV/JSON/JSONL BOM and CRLF | Exact accepted Arabic text, embedded CRLF, original file and row bytes, independent SHA-256 comparisons |
| Arabic identity | NFC/NFD-equivalent strings remain distinct and unchanged; no automatic correction |
| Ambiguous input | Literal/escaped duplicate keys, nested JSON inside CSV cells, invalid/truncated/overlong UTF-8 after a valid prefix |
| Cell bounds | Multibyte text at 20,000 characters remains exact; limit+1 is rejected with the original retained |
| Duplicate identities | Cross-format duplicate external IDs revoke both receipts even with a later invalid row; duplicate source inventory and source/segment tuples reject |
| Stale digest | BOM/CRLF/escape-spelling-only source changes invalidate bundles; recomputing a forged artifact manifest cannot bless modified outputs |
| Transcript revision | Format-independent source identity; timestamp/text/provenance changes invalidate every pair ID for that source, leaving other sources stable |
| Partial failure | Malformed/missing file isolation, no invalid legacy intake export, no partial transcript stdout, diagnostic write failure stays nonzero and cannot verify |
| Actual downstream adapter | Transcript question-only export reaches preparation unchanged and stays review-required without invented media or answers |

## Measured result and blocker

Reviewed starting SHA: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134).
On Python 3.13.15 / Windows, the new suite currently executes **21 test methods:
20 pass, 1 fails, 0 errors, 0 skips, 0 expected failures**. Ruff lint and formatting
checks pass. No production modules changed, so historical suites were not rerun.
The runner reports the exact tested candidate SHA and file hashes on each run.

The strict negative test
`CommandBoundaryTests.test_legacy_duplicate_key_diagnostic_does_not_echo_submitted_key`
exposes a pre-existing information disclosure in `tools/content_intake/cli.py`:
`unique_object` incorporates the submitted duplicate key into its exception and
the legacy CLI prints `str(exc)` as `error`. The synthetic canary appears in stdout.
Input rejection and exit 1 work, but diagnostic containment does not. The test is
deliberately **not skipped, inverted, or marked expectedFailure**. Its fix belongs
to the owning implementation lane; this lane may edit only its new QA directories.
Do not mark this suite PASS until the upstream diagnostic boundary is repaired.

Diagnostic bundle export is not atomic: an injected second-file write error may
leave a partial directory. This suite verifies the failure status, preservation of
the source, safe diagnostic, and failed recheck; it does not claim atomic cleanup.
Transcript per-source hashes describe supplied synthetic rows, not unavailable
recordings. No caller-supplied transcript digest verification API is invented.

The new suite is **not connected to shared CI dispatchers** in this lane; shared
CI YAML and dispatchers are outside ownership. B6/C6/D6 statuses are reported
separately on the Draft PR and must not be represented as execution of this suite.
Browser/PostgreSQL: **NOT_RUN** for this pure ingestion scope. Owner archives:
**NOT_SUPPLIED / NOT_ACCESSED**. No owner-data acceptance is claimed.

Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**;
**SCOPE_DEVIATION_HOLD**; **NOT_DEPLOYED**; U03/U10 **OWNER_APPROVAL_PENDING**.
