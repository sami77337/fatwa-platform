# FAST8 prepared-to-review contract bridge

Pure, deterministic development projection over the **existing** prepared fixtures.
No database, persistence, HTTP routes, input file loading, edits, answers, approvals,
role operations, migrations or deployment. Python 3.13; no additional dependencies.

```powershell
python -B -m tools.fast8_prepared_review --synthetic-fixtures-only
python -B -m tools.fast8_prepared_review --synthetic-fixtures-only --case batch-synthetic-json-1
python -B -m unittest discover -s tests/fast8_prepared_review -v
```

The default scenario returns JSON with exact source identity, full before/after
snapshots, snapshot hashes, reasons, and technical eligibility after each attempt.
Its 12 attempts include the existing eight rehearsal attempts, missing preparation
content, an unsupported cross-dimension join, a stale snapshot, and a changed source
fingerprint. Five are projected for `batch-synthetic-csv-1`; rejected attempts retain
identical state. The duplicate `batch-synthetic-json-1` never gains a draft.
Exit zero means the diagnostic scenario executed; it does **not** mean every attempt
was accepted or any governance gate passed. Missing acknowledgement/unknown selectors
exit 2. CLI is development-only and has no user-file input/output options.

## Existing contracts reused

- `prepared_pipeline` via `editorial_workbench.build_prepared_workbench`: original
  CSV/JSON/JSONL batches, all 11 prepared rows, four existing receipt drafts,
  rejected/pending diagnostics, and a malformed batch which has no selectable row.
- `fatwa_drafts.domain.transition`: actual preparation edges, revision increment,
  and required human title/answer checks. The bridge never calls `edit_draft` or
  fills missing title/answer to make a readiness test pass.
- `intake_workflow.contracts.next_review_status`: independent technical review labels.
- `workflow_invariants`: canonical encoding, full snapshots and state tokens.
- `revision_core.build_history`: validates existing and projected revision snapshots.
- `workflow_rehearsal.build_prepared_rehearsal`: executable scenario attempts and
  parity reference, preserving the existing separate review/preparation dimensions.

The legacy invariant replay's selector does not accept prepared cases, and its source
identity expects reference fields the prepared adapter does not supply. This adapter
uses the existing public helpers without monkeypatching or duplicating that engine.

## Exact identity and API

`inspect_case(case_key, synthetic_fixtures_only=True)` returns the fixed row's
identity, original snapshot and eligible **pure contract** actions. `project(request)`
accepts this envelope:

```python
from apps.fast8_prepared_review.services import SCHEMA, inspect_case, project
from apps.workflow_invariants.engine import state_token

case_key = "batch-synthetic-csv-1"
view = inspect_case(case_key, synthetic_fixtures_only=True)
result = project(
    {
        "schema": SCHEMA,
        "synthetic_fixtures_only": True,
        "case_key": case_key,
        "commands": [
            {
                "dimension": "preparation",
                "action": "draft_preparation",
                "source_identity": view["source_identity"],
                "expected_state": state_token(view["initial"]),
            }
        ],
    }
)
```

Every attempt requires the complete identity: batch, ordinal, case key, external ID,
format, exact raw batch SHA256, parsed-row SHA256, full prepared metadata hash and
ordered reference identities. Full state tokens pin preparation, revision, review,
and a hash of **all** history/intake content. Canonical comparisons distinguish bool
from integer. Missing/extra fields, changed fingerprints, swapped rows, stale states
and unsupported transitions reject without mutation. At most 32 attempts and 1 MB
of bounded JSON are accepted. There is no retry ledger: replaying an accepted command
against its old snapshot is stale. Each call starts fresh at the existing receipt.

Raw batch UTF-8 bytes, Arabic combining marks, CRLF and parsed strings are retained.
The parsed row is explicitly labelled `serialized_parsed_fields`, not an original
byte slice. Source offsets remain null. No timestamps are created or inferred.

## Explicit connection limits

`PURE_CONTRACT_ONLY` eligibility is **not operational authorization**. Review begins
with `SYNTHETIC_INITIAL_LABEL_NOT_PERSISTED`; it is not a fetched review state.
Reviewing a label leaves the draft revision untouched. Preparing a draft leaves the
review label untouched. The existing contracts permit this independence even when a
receipt has no answer or unresolved references; the bridge does not invent a policy.

- `preparation_to_review`: **NOT_CONNECTED** — no cross-dimension transition contract.
- `reference_to_wave7`: **NOT_CONNECTED** — even technically verified prepared
  references expose six C2 fields, missing the complete numeric Wave7 binding.
  No mapping is reconstructed from opaque IDs; the original diagnostic is preserved.
- `owner_workflow`: **NOT_CONNECTED / NOT_SUPPLIED** — no authority workflow supplied.
- Real PostgreSQL/owner archives: **NOT_RUN / NOT_SUPPLIED** for this pure lane.

Source fixture provider: `apps/editorial_workbench/batch_fixtures.py:synthetic_inputs`.
Exact per-input hashes are emitted at runtime and recorded in VALIDATION.md.
No acceptance claim about user-owned sources or a protected catalog is made.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.**
