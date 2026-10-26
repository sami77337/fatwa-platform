# FAST8 executable journey conformance

This development-only consumer contract selects a specific synthetic journey and
rejects stale or incomplete source identity before returning evidence. It reuses
`fast6_journey.run_integration`, the existing rehearsal/prepared/queue/triage/packet/
export services, permission DENY checks and the research bridge. It creates no
domain records, migrations, HTTP routes or new product functionality.

`scenarios.json` pins all 20 existing stock cases and the separate transcript
receipt scenario as observed at reviewed base
`92fa517ecdefe3f1a92a1ab145ff55943474df44`. Pins include every available identity
field and the original packet SHA256; the transcript instead pins its exact named
fixture input and prepared output. They are committed expectations, never refreshed
automatically. A deliberate source change requires review of new pins. Scenario
IDs are selectors, not cross-stage identities. Duplicate external IDs cannot join
different rows. Arabic, CRLF, timestamps and input bytes are handled by the existing
services without normalization.

```powershell
python -B -m tools.fast8_journey_conformance --synthetic-fixtures-only
python -B -m tools.fast8_journey_conformance --synthetic-fixtures-only --scenario intake-7
python -B -m tools.fast8_journey_conformance --synthetic-fixtures-only --scenario transcript-receipt
```

For consumer-defined requirements, pass UTF-8 JSON matching `scenarios.json` on
stdin with `--contract-stdin`. Only a bounded 64 KiB contract is accepted: no
source paths, uploaded content, module names or URLs are loaded. All fields are
strict; unknown fields, duplicate JSON keys/scenarios/stages, incomplete pins and
boolean/float aliases of integer identity values fail closed. The explicit
synthetic flag and existing production guard apply before fixture reads.

Each scenario's `required` array selects supported stage names. Requiring
`persisted_review`, `permission_case_binding`, or a stock queue/export stage for
the transcript produces `NOT_CONNECTED`, not success. The transcript contains no
draft and is never joined to stock cases. Prepared cases have an offline rehearsal
adapter; their existing rehearsal HTTP selectors still return 404.

| Result | Meaning | CLI exit |
| --- | --- | --- |
| PASS_WITH_GAPS | Requested technical boundaries checked; independent gaps remain | 0 |
| NOT_CONNECTED | At least one required boundary has no same-identity adapter | 3 |
| No report | Invalid/stale/missing evidence or failed invariant | 1 |
| No report | Invalid CLI arguments or absent opt-in | 2 |

Stage `PASS` verifies technical conformance, never substantive review, scholarly
approval, publishing or production readiness. Projected `REVIEWED_INTERNAL` is
transient; exported packets retain original snapshots and `persisted_review` is
not loaded. Permission checks remain DENY and have no case binding. Research
links are checked against explicitly synthetic snapshots and close on missing
catalog evidence. No live PostgreSQL result is claimed. HTTP/browser/PostgreSQL
execution remains `NOT_RUN` in service reports; owner archives are `NOT_SUPPLIED`.

The optional `extensions` names are declarative adapter slots, not claims that a
sibling lane exists. Missing probes report `NOT_CONNECTED` with execution
`NOT_RUN`. A reviewed integration may inject a read-only `BoundaryProbe` callable
through the Python API. It receives immutable `ScenarioAnchor` bytes and returns
`AdapterEvidence` with the same exact anchor and `PASS`, `NOT_CONNECTED` or
`NOT_RUN`. All scenario pins are validated before any probe executes. Probe PASS
means only that adapter's identity conformance check; it cannot replace a core
gap or satisfy a core required stage. Probes are trusted in-process code, not a
sandbox for arbitrary plugins. There are no real sibling adapters in this lane.

Run focused service, CLI and existing HTTP surface tests without a database:

```powershell
python -B manage.py test tests.fast8_journey_conformance.test_services tests.fast8_journey_conformance.test_cli tests.fast8_journey_conformance.test_http --settings=config.settings.test --noinput --verbosity=2
```

The repository's `tests` namespace requires explicit module labels with this
Django runner; the package-only label fails before collection. No UI was added,
so there is no new browser scenario. Existing B6/C6/D6 workflows are unchanged
and do not explicitly collect this new suite; the integration coordinator must
add these labels if CI collection is required. Their actual final-SHA statuses
are reported separately in the Draft PR, never inferred from local tests.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING. No owner archives or real/private
records were accessed. Rollback removes only the three owned FAST8 directories.
