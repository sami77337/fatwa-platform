# FAST6 permission policy gap engine

This is a reusable offline diagnostic service over the **existing** FAST5
permission laboratory. Every hypothetical request returns `DENY`, `allowed=false`.
It is not wired into Django settings, URLs, authentication, authorization or
workflow dispatch. No database, network, credentials, real actors or writes exist.

FAST5 already checked exact actor/action/resource IDs, synthetic resource bindings,
candidate roles and review-state compatibility. FAST6 adds aggregate evidence
coverage, explicit missing-evidence diagnostics, provenance membership checks,
requested transition-target validation, executable adversarial probes and canonical
JSON. The original S3 validator and fixtures remain unchanged.

## Service contract

```python
from apps.policy_gap_engine.services import (
    CandidateRequest,
    evaluate,
    build_report,
    canonical_json,
    inspect_evidence,
)

decision = evaluate(
    CandidateRequest("MUFTI", "synthetic::answer.draft", "synthetic::answer", "SYNTHETIC_REVIEW")
)
assert decision.effect == "DENY" and decision.allowed is False
report_bytes = canonical_json(build_report()).encode("utf-8")
```

`CandidateRequest` is a frozen hypothetical label tuple. The service accepts no
policy document, path, account or model. `evaluate` returns an immutable decision:

- `valid_combination` describes only known identifiers and compatible state/resource.
- `candidate_status` is `CANDIDATE_ONLY`, `NOT_CANDIDATE`, `INVALID`, or
  `EVIDENCE_MISSING`. Administrative peer status does not confer scholarly authority.
- `reason_codes` are deduplicated and sorted; Arabic messages from FAST5 are
  retained exactly. All decisions include `DENY_DEFAULT`, `POLICY_PENDING`, and
  `EVIDENCE_MISSING`. Pending acceptance and absent evidence are independent gaps,
  so both can apply to the same request.
- Existing review actions have no supplied permission candidate mapping:
  `REQUEST_POLICY_EVIDENCE_MISSING`. Their valid state edges remain unauthorized.
- All known transitions carry `TRANSITION_UNAUTHORIZED`; an exact optional target
  must match the existing contract or produces `TRANSITION_TARGET_MISMATCH`.
  `workflow_target` is the documented destination, never a state mutation.

`build_report()` evaluates 15 fixed synthetic request probes and eight in-memory
inventory mutation probes. Optional input is a tuple of 1–256 `CandidateRequest`
objects; it replaces the request list but retains the independent built-in probes.
An invalid batch envelope raises fixed `ValueError("INVALID_REQUEST_ENVELOPE")`
before reading sources. Malformed individual identifiers produce DENY diagnostics.
Unknown submitted values are never echoed in JSON. Known synthetic resource labels
and IDs come directly from FAST5, without normalization or reconstructed mappings.

`adversarial_checks.status=PASS` means the supplied negative probes observed DENY
and their expected request reasons, or the original validator rejected an in-memory
mutation. This is not source acceptance or policy approval. Failures are reported
with actual observed reason codes. Mutations never modify the pinned files or
become the inventory used to evaluate requests.

## Provenance and coverage

Base: FAST5 `0eef6b29943364dddae35a193b356ab79a2e2b5e` (Draft PR #116).
Reused S3 origin: `88c411852d1a90e62ec71ab1c9ae2278f72d0c76`.

| Fixed fixture | SHA256 |
| --- | --- |
| `apps/permission_lab/upstream/synthetic_inventory.json` | `40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4` |
| `apps/permission_lab/upstream/synthetic_review_excerpt.json` | `266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d` |

The FAST5 loader verifies five pinned artifacts before importing the original S3
validator. FAST6 also runs S3 `validate_inventory` against fixed local paths and
checks each row's policy token and source-record membership in the pinned invented
excerpt. The report labels this `SYNTHETIC_ID_MEMBERSHIP_ONLY`; it does **not** verify
the content of any historical permission, reviewed source or approval clause.
The bytes are rechecked after report evaluation. Source failure yields
`EVIDENCE_UNAVAILABLE`, DENY, no request results, no verified synthetic coverage,
and `adversarial_checks.status=NOT_RUN`; error details and local paths are omitted.

The four invented action rows and one transition are reported separately from
historical availability. The historical 70 rows, 58 transitions, U03's 48 clauses,
U10's 28 clauses, reviewed original sources and owner acceptance are **not supplied**.
Historical coverage is zero supplied, never 4/70 or 1/58. Clause counts are only
documented expectations from AGENTS.md; no clause text or individual approvals
are fabricated. `policy_approval_verified` and `source_acceptance_passed` stay false.

## Verification and execution

Implementation sequence: inspect existing services; add failing gap/evidence tests;
implement the source adapter and evaluator; add CLI and negative probes; run focused
new and affected tests; perform one independent final review; fix findings; publish
one Draft PR to the FAST5 integration branch. No migration or data conversion is
needed. Rollback consists only of removing these three new directories.

Use the pinned Python 3.13 environment from the repository root:

```console
python -m unittest tests.policy_gap_engine.test_services tests.policy_gap_engine.test_evidence tests.policy_gap_engine.test_cli -v
python manage.py test tests.permission_lab.test_sources tests.permission_lab.test_services tests.permission_lab.test_views tests.wave7_foundation.test_contracts --settings=config.settings.test --noinput
python -m tools.policy_gap_engine --synthetic-only
python -m ruff check apps/policy_gap_engine tools/policy_gap_engine tests/policy_gap_engine
python -m ruff format --check apps/policy_gap_engine tools/policy_gap_engine tests/policy_gap_engine
```

CLI details and exit codes: [tools README](../../tools/policy_gap_engine/README.md).
The existing shared CI uses explicit older suites and is not modified by this lane;
CI success is separate from running the new engine suite explicitly. No PostgreSQL,
browser or historical archive acceptance is claimed by this offline engine.

Measured before the delivery commit, on the exact FAST5 base above plus these new
files, using Python 3.13.17 / Django 5.2.18 in the existing external environment:
26 new tests passed in 36.367 seconds; 38 directly affected FAST5/intake tests passed
in 11.969 seconds. Ruff lint/format and staged whitespace checks passed. Initial
red tests correctly failed for the absent engine and CLI before implementation.
One independent final read-only review found no actionable issues and independently
ran all 26 new tests successfully in 33.033 seconds.

The actual default CLI output is 42,905 UTF-8 bytes, with SHA256
`65a0bb9484a6eff314447e1d8966bc1c5401dff626068eaa32c77e5b1e400f90`:
15 hypothetical requests, 23 negative probes evaluated, zero failed probes,
DENY throughout. The report contains no timestamp, local path or runtime Git lookup.
Final committed-SHA and remote CI observations belong in the Draft PR, separately
from these local measurements.

**Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED / GATES_HOLD.**
