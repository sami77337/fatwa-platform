# V14 batch reference-ledger contract

`apps.source_rights.batch.reference_projection_for_locked_case` is an internal
context manager, not an HTTP endpoint or authorization entry point. No registration,
migration, policy grant or persistent cache is introduced.

```python
with canonical_authorized_case_transaction(...) as (case, actor):
    with reference_projection_for_locked_case(
        case=case,
        identities=[(edition_id, source_row_id)],
        usages=("READ",),
    ) as sources:
        # sources[(edition_id, row_id)] == canonical citations._source(...) exactly
        # Independently apply the current custom policy and identity checks.
        # Compose rows/counts/facets only from authorized sources.
        response = compose(sources)
        final_custom_policy_collection_check(response)
    # Only now may this response escape to its ordinary serializer boundary.
    return response
```

The signature above is the actual API; the other function names are illustrative
consumer obligations, not new services. It requires an existing atomic transaction
and acquires the canonical case row lock defensively. The caller must already
establish synthetic-owned DB, identity, case scope, action authority, and all
ordinary independent publication/preview/custom research policies. Holding a
case object is not authority. No external or privileged SQL prevention is claimed.

Inputs: list/tuple of at most256 exact positive integer identity pairs, and a
nonempty list/tuple of ledger uses READ/CITE/RELATE/PREVIEW_METADATA. Unsupported
uses such as PUBLISH/FULL_TEXT remain denied. Duplicate identities are deduplicated.
The returned dict contains **only** registered, currently independently approved,
exact source/edition/path/hash grants in this case. The source remains TOC metadata,
not original text or a general classification. Empty/denied sets reveal no metadata.

Canonical resolution uses the existing pure `resolve`, `Heading`, `SnapshotCatalog`
and `SourceIdentity` validation, with bulk bounded ancestor reads and exact pair
queries. Edition/work metadata, original root-to-target titles, maximum depth5,
printed position, archive/input pins and canonical JSON hash match existing
`citations._source`; malformed parents/cycles/edition crossings are rejected.

After the consumer finishes building the response, **fresh** database reads repeat
source, latest revision and review-action checks for every yielded member. Changed
source, new pending revision, revocation or expiry invalidates the entire projection
with `current_source_rights_required`. This intentionally fails the entire response
rather than leaving obsolete totals/facets or silently returning an earlier page.
A defensive copy separates consumer mutations from validation receipts. The mapping
must not be retained across requests/transactions; it is not a grant token.

## Custom policies remain separate

This adapter calls no custom ResearchRights callback and does not cache its decision.
The consumer must still prevent SEC14-01-style callback reentrancy: a callback while
checking a later result may revoke an earlier result's custom policy. The exact
whole-collection policy/identity boundary, and serialization-time expiry boundary,
remain required. A successful ledger projection alone does **not** fix SEC14-01 or
authorize ranking, count/facet disclosure, relation access or publication. Concurrent
canonical rights writes serialize on the case row; external DB changes are outside
the application perimeter.

## Focused evidence and historical failures

Tests: `apps.source_rights.test_v14_batch.BatchReferenceTests`, isolated synthetic
PostgreSQL only. Coverage includes canonical multi-position/mixed-edition parity,
missing registration/review, independent grants per edition, cross-case isolation,
new pending revision, source/path mismatch, in-composition rights revocation,
expiration after composing metadata/counts, unsupported uses, disabled configuration,
invalid/bounded input and defensive mapping copies.

Measured five canonical positions: **9 SQL queries for both fresh passes including
the case lock**, independently of the number of positions at that hierarchy depth.
The structural upper bound is17 queries (two passes of up to5 catalog levels plus
3 ledger queries and one case lock), not an endpoint latency/scalability claim.
No browser or integrated search improvement is claimed by this service-only test.

Initial PG17 run:6 passed,3 failed because test fixtures attempted immutable catalog
updates and invoked a top-level guarded mutation inside an atomic read. These were
fixture errors; catalog immutability and ownership guards were preserved. Updated
negative fixtures use changed canonical snapshots at the read seam and an explicit
synthetic in-transaction append-only revocation. Affected three passed. Exact pair
query changed subsequently to avoid a cross-product; final PostgreSQL17.12 run **10/10 PASS (3.562s)**. PostgreSQL18.7 ran
**9/9 PASS (3.247s)** on the exact-pair implementation, then the newly added
mixed-edition check **1/1 PASS (0.439s)**, with no product change in between.
Ruff check/format passed. Local logs: `/tmp/v14-batch-pg17-final.log`,
`/tmp/v14-batch-pg18.log`, `/tmp/v14-batch-pg18-mixed.log`; these are execution
logs in this environment, not remote CI artifacts.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No acceptance,
production permission or new completion estimate.
