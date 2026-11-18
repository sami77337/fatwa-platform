# V14 final-boundary repair candidate

Base: `e8ebef812d7e7cd3411252a8fe11fedb0ab2cc94`, PR #233.

The independent `b52ca4a77c73401903f62a500d59f851f3296e97` report and
original failure evidence are retained unchanged. SEC14-02 and SEC14-03
are repaired here; runtime clearance remains pending exact-head CI and review.

* Evaluation propose/decide/history project data before the last authority
  callback, then revalidate the actor after that callback and before atomic
  commit/return. Late identity loss therefore rolls back writes.
* Direct audio/PDF READ_MEDIA/CITE deadlines propagate conservatively into
  every enclosing strict media boundary. The clock is checked after the final epoch
  read, inside the case transaction, without another permission callback.
  Nested scopes reset on errors; deadlines are not cached permissions.
* Existing independent boundary/recovery tests and ten additional independent
  identity, locator metadata, byte-return and rollback tests join V14 CI.

Execution was continued outside Codex Cloud with explicit owner permission.
Only relevant files were materialized via the authenticated GitHub connector;
baseline product blobs were verified against exact-head Git blob hashes.
The publication overlays the complete existing Git tree, preserving other files.
Local Ruff and Python compilation pass. PostgreSQL/Django are unavailable in
the local workspace; protected Chrome cannot create its required socket there.
No local PG17/18 or browser runtime success is claimed. The existing hosted
matrix is the runtime verification venue; no sandbox, timeout or retry relaxation.

No earlier failure is erased. Startup ROOT_CAUSE_UNKNOWN, human ranking review
PENDING, PDF engine-selected-page NOT_VERIFIED and original-source provenance
limits remain. No acceptance percentage or scope completion is inferred.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
No main merge, deployment, real data, external delivery, or automatic approval.
V14 only; no V15.

## Compatibility correction

The first rescue candidate f1eed92 failed one of 120 V13 tests per PG major: 
`test_collection_rechecks_timed_expiry_after_later_legacy_result_projection`.
Its global deadline retention rejected the whole library instead of filtering
an expired earlier item. The correction keeps strict media deadlines by default;
only library preview delegates to its existing emitted-result deadline list and
post-epoch clock. The original regression test is unchanged. V13 run 44257563012
is retained as failure evidence, not a browser startup failure or a skipped test.

## Protected layout measurement

On `7d03f14561bc9612a1e7588c3b4a706170313063`, V7 run 44258774857
passed 34 functional tests but the PG17 protected browser observed scrollWidth
509 at viewport 320 on requester attachment preview. Available artifacts contain
no DOM/trace/screenshot identifying the overflowing element. ROOT_CAUSE_UNKNOWN.
The page loads external CSS, while the prior capture started after
DOMContentLoaded without asserting stylesheet readiness. This is a test-contract
risk, not proof of the historical cause. Capture now records initial readiness,
width and CSS presence, waits for the same-origin stylesheet within the existing
Playwright timeout, and retains the identical width assertions. Failures emit
bounded element geometry/style diagnostics, not text or media. No retries,
extra timeout, sandbox change, or product CSS hiding is introduced.
