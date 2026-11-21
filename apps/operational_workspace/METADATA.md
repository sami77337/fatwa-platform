# Organizer metadata and reviewed classification

This development-only unit implements owner point **94**, `SPEC-U03-012`, over
the existing `OrganizationRevision` and `CaseClassification` journals. It uses
the actual `ORGANIZER`, `ORGANIZER_ADMIN` or `MUFTI` identity from the configured
directory. It does not alter the MUFTI-only canonical answer/decision boundary.

## Configuration and separate grants

`FATWA_OPERATIONAL_METADATA_ENABLED` defaults to false when absent. The workspace
and organization flags are also required, with `FATWA_PRODUCTION=0` and an owned
synthetic database. Integrating settings must declare the new flag as false.

`READ_CASE` and `READ_METADATA` are necessary on the target case. `EDIT_TAGS` and
`EDIT_QUESTION_TYPES` are separate `CASE_OPERATIONAL_SECTION` grants for the
`metadata` section. Neither changes internal notes. Historical notes remain in
their immutable rows; new metadata revisions have an empty note.

`READ_CLASSIFICATION` and `BIND_CLASSIFICATION` use an exact resource:

```json
{
  "kind": "CASE_CLASSIFICATION_VERSION",
  "case_id": "<target-case UUID>",
  "tree_case_id": "<tree-owner case UUID>",
  "tree_id": "<tree UUID>",
  "version_id": "<reviewed version UUID>",
  "digest": "<version digest>"
}
```

The taxonomy feature, configured `TaxonomyAuthority`, current scope and
`READ_CASE` on the tree's owning case are independently required. Existing domain
checks remain: `READ` on the tree, `USE` on the tree for a write, `BIND` on the
target case and exact version, and `READ` on an existing binding before its
selection, author or reason is returned. A version needs an intact independent
human `APPROVE` record. Unavailable versions and binding details are omitted.
No tree creation, tree approval, migration, account administration, scholarly
answer creation/approval, delivery or publication permission is supplied.

## Persistence, native access and revocation

Separate native forms edit tags/types and bind one primary concept plus up to
12 distinct additional concepts from an exact reviewed provisional version.
Existing organization validators and taxonomy SQL guards remain authoritative.
Binding requires an approved current answer under the existing taxonomy contract;
tags/types can be organized before an answer without delaying the Mufti.

The metadata index also retains authorized cases with no pending operational
task. Pending-lane counts retain their original meaning. Pages omit internal
notes and preserve the original question, facts, answer, recording, approval and
delivery history.

CSRF, strict field admission, source revision/evidence pins, metadata/binding CAS,
explicit classification confirmation and command identifiers protect requests.
Identical metadata retries do not append again. A binding retry must match the
same current last binding, actor, input and source pins; changed input or an
intervening binding conflicts. Every retry requires current grants.

Sorted canonical locks and the graph lock remain held through final rendering.
The pre-read watermark includes scoped trees, concepts, versions/reviews,
metadata and bindings. An authorized append adds exactly one verified row to
the expected source set; a fresh broad snapshot cannot hide an unrelated write.
Domain callbacks precede final policy pins, and all callbacks finish before final
source, directory, permission and expiry checks. Late revocation, policy changes,
source changes or render failure roll back the append and discard the page.

## Proof integration

Behavior label: `apps.operational_workspace.test_metadata`.

Recovery label: `apps.operational_workspace.test_metadata_recovery`; helper
`apps.operational_workspace.metadata_recovery_support` implements `populate()`
and `verify_restored(pins)`. `TABLES`, `FUNCTIONS` and `TRIGGERS` are empty because
storage is already registered by organization/taxonomy. Verification supplies
fresh grants, runs named denials, performs a real positive read after the denials,
and compares unchanged restored source/history fingerprints. Pins contain no
credential or saved permission set.

Protected browser: one journey in
`apps.operational_workspace.browser_metadata.OperationalMetadataBrowserTests`.
Output: `.local/qa/functional-continuation/operational-metadata-browser/result.json`,
trace and 320/1280 screenshots. This document asserts no browser success; the
integrating hosted run must execute the class before point 94 receives credit.

## Limits

The tree remains `SYNTHETIC_PROVISIONAL_FIQH`, without approval of a global
religious taxonomy. D-054/D-067 support this explicit development path; detailed
production permissions, overrides, account administration and mutual grant/revoke
boundaries remain outside it. Source acceptance and release gates are unchanged.
This unit does not claim points 95, 96, 97, 98 or 99.
