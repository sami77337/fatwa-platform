# S3 offline contract validators — issue #4

Development-only documentation tooling. NOT_DEPLOYED / GATES_HOLD.
No commits, pushes, PRs, merges, deployment, active grants, Django permissions,
migrations, runtime APIs, workflow dispatch, AI calls, or private-user operations.

This lane owns only contracts/**, tests/contracts/**, and docs/contracts/**.
The checked-out branch is codex/s3-contract-validators-20261013. The exact base
SHA and actual checks are recorded in TEST_RESULTS.md and validation-evidence.json.

## What is implemented

The standard-library Python validator reads a caller-supplied local JSON inventory,
checks the bundled closed JSON Schema and cross-record policy constraints, hashes
its exact bytes and explicitly supplied original-source files, and emits one JSON
report to stdout. Nothing in an action or transition is executed. Files, imports,
callbacks, or network destinations cannot be selected by inventory contents.

Source mode requires an independently supplied inventory SHA256 pin. Every record
has a document ID and original record ID. Each source document declares an exact
SHA256 and must be provided separately through --source ID=PATH. Undeclared source
arguments, unknown record references, reused original record IDs, duplicate IDs,
missing files, bad hashes, and unknown fields fail closed. Hashes establish byte
identity; they do not establish owner approval or prove a normalized record matches
its original contents. Reports therefore always retain:

- validation_scope: STRUCTURE_POLICY_HASHES_ONLY
- source_acceptance_passed: false
- policy_approval_verified: false
- record_content_binding: NOT_VERIFIED_REQUIRES_REVIEWED_SOURCE_ADAPTER
- runtime_executable: false, active_grants: 0, grant_effect: NONE
- owner_approval: OWNER_APPROVAL_PENDING
- gate_b: NOT_PASSED, gates_c_d_e: HOLD, phase01: BLOCKED

The 70 historical rows and 58 transitions were not supplied. They have not been
reconstructed. Source-mode completeness requires exactly 70 actions, including
37 DOMAIN_STATE and 33 UI rows, with 55 UNMAPPED_HOLD and 15 MAPPED_DRAFT,
and exactly 58 transitions. Every action must remain DENY_DEFAULT with binding
NONE_CANDIDATE_BINDING_ONLY and grant_effect NONE. Candidate roles are metadata;
MAPPED_DRAFT never activates them.

D-067 is locked as MUFTI and ORGANIZER_ADMIN at ADMIN_PEER and ORGANIZER at
CONFIGURABLE_LOWER. Only MUFTI can be a scholarly creation/approval candidate.
Transition candidates cannot expand their referenced action's candidates.
The current documentation token is
D-067:D-068:U03-U10:OWNER_APPROVAL_PENDING:20261013. It is a fixed snapshot
identifier, not a credential, runtime authorization token, or accepted owner policy.
Every action and transition must match it. Policy activation remains forbidden.

P00-03::case.project and P00-03::delivery.hold must be INTERNAL_ATOMIC_EFFECT
records in the DOMAIN_STATE group, attached to parent transaction P00-03, with
zero candidate principals. They cannot be callable, service identities, or transition
dispatch targets. Other actions cannot impersonate those effects. All transition
enabled flags remain false. Historical-answer mutation is rejected.

D-068 appears only as DISABLED AI, deferred V1 human-reviewed inline citation
suggestions, and V2_DEFERRED external ChatGPT. There is no AI implementation.

## Input format

The complete field contract is contracts/inventory.schema.json (JSON Schema
2020-12). Every object has additionalProperties: false and requires all its declared
fields. No custom extension fields, wildcard roles, service principals, or hidden
grant fields are accepted. The Python checker evaluates the subset used by this
schema: type, const, enum, properties, required, additionalProperties, items,
minItems/maxItems, uniqueItems, minLength/maxLength, and pattern. It does not
resolve $ref, load remote schemas, or implement a general JSON Schema engine.
The schema-keyword test detects unsupported future schema additions.

Top-level fields are schema_version, fixture_kind, policy, source_documents,
actions, and transitions. Version is 1.0. fixture_kind is SOURCE_INVENTORY or
SYNTHETIC and must match the explicit CLI mode.

An action records its action_id, row_type, mapping_status, record_kind, operation,
deny_default, binding, callable, parent_transaction, source_ref, policy_token,
candidate_principals, grant_effect, and historical_answer_mutable.
A transition records its transition_id, from_state, to_state, action_id, enabled,
source_ref, policy_token, candidate_principals, grant_effect, and
historical_answer_mutable. Explicit candidate principals contain only kind ROLE
and a name from MUFTI, ORGANIZER_ADMIN, ORGANIZER.

Input files are limited to 4 MiB each. UTF-8 JSON must reject duplicate keys,
NaN/Infinity, oversized input, and excessive nesting. Reports cap diagnostics,
never copy arbitrary field values or parser excerpts, and contain no input file
paths. A source record ID is an identity reference; state labels and action
operation classifications still require independent comparison with reviewed
originals when their actual format is supplied.

## Reproduce with Python 3.13

No dependency installation or PostgreSQL instance is needed for this offline lane.
Run these commands from the repository root with an existing Python 3.13 runtime.
On Windows, use py -3.13 instead of python if appropriate.

Run the authored Python test suite:

    python -B -m unittest discover -s tests/contracts -v

Optional artifact-only checks with an existing Node runtime:

    node --test tests/contracts/test_artifacts.mjs

These eight tests verify JSON/schema/fixture integrity and exact fixture hashes.
They do not run or substitute for the Python permission/workflow negative tests.

Emit the default missing-source report:

    python -B -m contracts

Expected behavior for this command is JSON status BLOCKED with
SOURCE_CONTRACT_MISSING and exit code 2. This is an expectation of the code;
it has not been observed on this worktree because Python is unavailable.

Validate the deliberately small synthetic fixture:

    python -B -m contracts tests/contracts/fixtures/synthetic_inventory.json --synthetic-fixture --sha256 40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4 --source synthetic-review=tests/contracts/fixtures/synthetic_review_excerpt.json

Expected successful synthetic status is SYNTHETIC_VALIDATED, never source
acceptance. Supplying that fixture without --synthetic-fixture fails mode and count
checks. The fixture contains four actions and one transition; the two known effect
IDs exercise stated rules, and their test content is invented and explicitly marked.
No complete historical inventory exists here.

When reviewed sources become available, normalize them through an independently
reviewed adapter and retain document/record IDs. Invoke source mode with an
independently obtained inventory hash and every original file:

    python -B -m contracts PATH_TO_INVENTORY --sha256 INDEPENDENT_INVENTORY_SHA256 --source REVIEW_ID=PATH_TO_ORIGINAL

Repeat --source for each declared original document. Do not calculate a pin from
an untrusted input and treat it as independent approval evidence. Source files are
never fetched automatically. Passing source mode yields DOCUMENTATION_VALIDATED
for structure, policy invariants, and supplied byte hashes only. It cannot close gates,
accept U03/U10, authorize product operations, or establish source-record correctness.
The reviewed-source adapter and human comparison remain required.

Exit code 0 means these offline checks passed in the explicitly requested mode;
2 means INVALID or BLOCKED. Standard argparse usage errors go to stderr and also
return 2. Unknown options do not execute any operations. The Python API accepts
validate_inventory(...) for the same inert report or inspect_structure(...) for
fixture-based structural diagnostics without file/provenance verification.

## Integration handoff to S0

S0 may consume these reports as documentation evidence after independent review.
Do not import the candidate-role inventory into Django permissions, expose draft
transitions as endpoints, or bind DOMAIN_TRANSACTION to an account or service.
No backend integration, database migration, or root dependency change is included.
The source contracts, their original format, independently pinned hashes, reviewed
record adapter, and a runnable Python 3.13 test environment remain outstanding.
No positive complete-source acceptance test is claimed; it needs the real reviewed
70/58 records. The fiqh TOC ZIP is not an RBAC/workflow source and was not used.
