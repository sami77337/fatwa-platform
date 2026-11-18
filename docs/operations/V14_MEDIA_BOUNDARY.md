# V14 private-media composition boundary

Internal regression at product `32cfcb7f3a59b04e153dca2a627da21e9b29f739` proved
that a later PDF permission callback could revoke an earlier timed-audio grant
while canonical approval or private release still succeeded. Both original
negative tests failed on PG17.12 and18.7; their positive mixed-answer control
passed. This is same-transaction policy mutation, not concurrent SQL. Test-only
commit `d3a1eef4d8bb9974383c97c7ff4cfb98f1d0400f` records the unchanged adversaries.
The hosted101 checks and complete protected journey on that head did not include
this challenge and cannot clear that head retrospectively.

## Required adapter contract

`TimedMediaRights.media_projection_epoch()` now supplies a nonempty bounded string
covering **every private-media authorization input**. Read it atomically and without
side effects, and change it on every relevant pin, permission, identity, scope or
expiry-bound update. This is distinct from a TOC-only `projection_epoch()`. A
constant TOC marker must never authorize audio/PDF snapshots. Unversioned or
malformed media adapters fail closed. No production adapter or implicit grant is
created; only the two existing synthetic test adapters implement this contract.

The first exact READ_MEDIA/CITE check enrolls the configured policy object and its
media epoch in every enclosing case-use scope. Subsequent checks and final scope
exit require the identical object and epoch. There is no final permits loop that
can mutate another grant after checking it. Existing exact media hash/version,
case/actor, READ_MEDIA and CITE predicates, deadline checks and immutable history
remain mandatory. An epoch is an additional veto, never an authorization cache.
Canonical mutations are checked before the case transaction exits, so a late
revocation rolls back approval/release/event effects. Nested reads contribute to
all outer scopes. Public-looking library preview has an outer scope over the
whole results/counts/facets/page projection and converts denial to its existing
unavailable response. Staff publication collections retain all case scopes until
their collection returns.

Policy revocation must still serialize with the canonical case lock. The adapter
must honor the atomic, side-effect-free version contract; arbitrary malicious
policy code cannot be made trustworthy by repeatedly calling it. No claim covers
external privileged SQL, production policy providers or a distributed rights cache.

## Focused execution and historical failures

After the implementation change,57 affected checks passed on PG17.12 (55.837s)
and18.7 (55.453s): the three original cross-kind tests, canonical timed/PDF use
boundaries and their service/integrity tests. A second focused five-test batch
passed malformed/unversioned policy denial, late post-locator revocation rollback,
equal-epoch policy replacement denial and the strengthened V13 expiry adversary;
the library test initially failed setup because its fixture omitted an explicit
source-rights authority. That fixture is corrected without relaxing strict rights;
its affected rerun and final hosted execution are recorded by integration.

External security re-review of this new boundary is PENDING. Gate B NOT_PASSED;
C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No acceptance or percentage update.

The first library-fixture correction then exposed nested override restoration:
the temporary authority context discarded the inner preview policy before browse.
Both setup errors are retained in local integration logs. Keeping the explicit
synthetic authorities alive for the entire test corrected that setup; the single
library-return adversary then passed on PG17.12 (3.080s) and18.7 (3.156s).
The exact original three reproducer assertions remain unchanged. Added checks
require actual revocation execution and transaction rollback, reject an equal-epoch
replacement policy object, and reject a missing/malformed media epoch.
