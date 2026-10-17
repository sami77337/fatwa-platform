# Wave7 E5 Foundation Implementation Plan

Goal: freeze the authorized synthetic-only storage/guard contract for dependent
lanes, using accepted base 8a362b0ff69dadbac288d05a7cf33d5fdd36951e.
Architecture: four new workflow models in a separately registered dev/test app;
a single guard validates explicit environment acknowledgement and actual
PostgreSQL ownership before opening a synthetic write transaction. PostgreSQL
constraints/triggers protect identity, original snapshots and append-only events.
Tech stack: existing pinned Django 5.2/Python 3.13, PostgreSQL 17/18, Node 24.
Spec: parent finalized Wave7 v1.0 dispatch and six final overrides, 2026-10-17.
Execution: native implementation in the requested isolated Cloud worktree;
parent arranges independent review. No new approval/preferences round.

Constraints: no changes to public/base settings, middleware, security, auth,
sessions/admin, URLs/HTTP writes, real catalog/data, credentials, deployments,
main or Wave8. Existing Wave6 worktree/head must remain unchanged.

## Freeze decisions

- Row/reference ordinals start at 1, bounded at 1000/100 respectively.
- Scope/source configuration are fixed module constants, not service arguments.
- UUID primary keys; duplicate external IDs allowed; invalid IDs may be NULL.
- Batch retains exact original bytes and SHA; item/ref JSON preserve original
  values. Invalid Unicode/NUL envelopes reject before storage; valid question
  spaces, marks, tabs/newlines remain exact. Invalid individual rows stay present.
- Runtime writes require explicit flags, acknowledgement, literal loopback,
  exact configured synthetic names/role, PG17/18 and an immutable ownership
  marker initialized only in an empty database. Known owned data remains usable.
- `synthetic_atomic()` calls the sole guard before atomic(), sets a local DB
  write permit, and rolls back all writes on failure. Direct unguarded DML fails.
- Pure contract owns status enums, allowed transition graph, payload bounds and
  idempotency hash decision; E1/E2 implement services, locking/retry and CLI later.
- Three fixed synthetic reference mappings; only complete allowlisted identity
  dictionaries may accompany VERIFIED/citation. Actual evidence resolution is E3.
- E5 tests use `tests/wave7_foundation/`, avoiding E1's owned intake test path.

## Tasks and evidence

1. [x] Write pure contract/environment regressions RED; implement contracts,
   fixture/config, guard structural validation; run exact pure labels GREEN.
2. [x] Add guard-owned database bootstrap and transaction permit. Register only
   `config.settings.wave7_development` / `wave7_test`; pre-migration guard rejects
   unknown or disabled targets before schema mutation. Add a bounded owned-test
   lifecycle using Django runner and exact-resource cleanup, no keepdb reuse.
3. [x] Write DB constraint/guard/rollback/concurrency tests RED; implement models,
   initial schema and immutable/guard triggers. Test on disposable PG17 and PG18.
4. [x] Check migration discovery, makemigrations --check, migration application,
   preserved default app/middleware/settings/HTTP-denial contract. Add actual
   foundation labels to existing CI, with pure Windows/Linux and isolated PG jobs.
5. [ ] Document exact frozen fields/signatures, source/config trust boundaries,
   actual commands/counts and pending dependent services; commit/push one coherent
   foundation increment and publish Draft PR to the accepted development base.

Review focus: unsafe connection overrides; unknown nonempty DB; guard called
inside an existing transaction; invalid source identity with a VERIFIED status;
case-preserving originals and duplicate/blocked rows; concurrent unique-key
races; partial write rollback; immutable event/source fields; stale test DB
reuse and exact-resource cleanup. These receive explicit regression coverage.
