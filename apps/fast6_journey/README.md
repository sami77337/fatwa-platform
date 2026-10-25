# FAST6 deterministic synthetic journey

Development-only executable integration over FAST5 baseline
`0eef6b29943364dddae35a193b356ab79a2e2b5e`. No app registration, URL,
settings, dependency or upstream implementation changes are required.

```console
python -B -m tools.fast6_journey --synthetic-fixtures-only
python -B manage.py test tests/fast6_journey --settings=config.settings.test --noinput
```

Use Python 3.13 and the repository's pinned requirements-dev.txt. The CLI emits
canonical UTF-8 JSON to stdout only; it accepts no source path or output path.
`run_journey(synthetic_fixtures_only=True)` returns immutable `JourneyReport`
bytes, `.sha256`, and a detached `.payload()` dictionary.
`verify_journey(raw, synthetic_fixtures_only=True)` bounds and exactly replays
the bytes rather than trusting a supplied hash. Guards reject production and
anything except explicit boolean synthetic acknowledgement.

The runner invokes existing transcript, preparation, diagnosis, queue, revision,
triage, research bridge, rehearsal, permission and packet/export services. It
checks complete case identities (input digest, exact source digest, key, batch,
row ordinal or byte slice), original data, revision identities, queue neighbors,
source slices, CSV JSON-cell round trips and exact consolidated export replay.
Repeated external IDs never establish a join. Malformed/rejected records remain
visible; missing references never produce a catalog link. Catalog verification
uses only the existing fixed synthetic SnapshotCatalog, explicitly supplied.

The result `PASS_WITH_GAPS` means executed invariants passed, not that a full
product workflow exists. Mismatches raise an error and the CLI exits nonzero.
Expected rejected fixtures are successful negative checks. Connections lacking
an existing adapter remain explicit:

| Boundary | Evidence |
| --- | --- |
| Transcript → prepared | Exact export bytes and identity pass; no draft because media and references are absent. Answers remain in the transcript report only. |
| Transcript → stock queue | **NOT_CONNECTED**: queue loads independent fixed fixtures; no automatic ingestion of transcript output. |
| Queue → triage → packet/export | Exact per-case source identity and original snapshots verified for 20 records. |
| Prepared → rehearsal | **NOT_CONNECTED**: rehearsal only accepts the nine original fixture keys. |
| Rehearsal → export | **NOT_CONNECTED**: export retains originals, not projected review events. |
| Permission → case | **NOT_CONNECTED**: hypothetical resources are not case IDs; every decision is DENY. |
| Prepared reference → catalog | Existing incomplete evidence remains unverified; no guessed source or edition. |

HTTP tests follow existing links and preserve selected revision 7 (history is
1, 2, 4, 7, 9, 11). They reject invalid revision/filter identities, remote access
and POST/PUT/PATCH/DELETE. `SimpleTestCase` forbids database access. The browser
test reuses the actual research browser journey and labels its catalog as a
fixed synthetic test double. Missing Node/Chrome produces explicit NOT_RUN,
not a browser pass. Browser automation uses temporary profile files outside the
repository; application traffic is restricted to loopback GET/HEAD.

The CLI report always says HTTP/browser/PostgreSQL/owner archives **NOT_RUN**:
the offline command does not execute those checks. Separately executed test
results belong in validation evidence, never inferred into a later CLI report.
Services do no writes, subprocesses or network calls; tests prohibit those
operations and prohibit implicit Django catalog lookup.

Existing limitation outside this lane: ordinary workbench HTML uses literal
CRLF, which HTML normalizes. Packet HTML/JSON, triage and research preserve exact
CRLF and Unicode; the integration tests verify those paths. No upstream page
was changed to hide this limitation.

Owner archives, live PostgreSQL evidence, historical 70 permission rows / 58
transitions, U03/U10 acceptance and persisted-review linkage were not supplied
to this journey. Synthetic source pins are not proof of owner archive content.
Internal REVIEWED_INTERNAL is a rehearsal label, never scholarly approval.

**Gate B NOT_PASSED · C/D/E HOLD · Phase01 BLOCKED · SCOPE_DEVIATION_HOLD · NOT_DEPLOYED.**
