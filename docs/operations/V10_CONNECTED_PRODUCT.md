# V10 connected product integration

Base: PR #228, `12840d54c263e63b214ce72eff1d8b4f93f9900e`.
Integration branch: `codex/20261117-v10-integration`. No main merge.

The current case now stays visible across source history, attachments, research,
answer parts, review, private release, delivery and independent publication.
The opt-in requester portal presents approved availability separately from provider
acceptance and signed part delivery. The source inbox and delivery controls use
the existing case, evidence, answer and queue records. Anonymous-looking library
preview requires expiring, exact synthetic publication/reference grants; private
transcripts and withdrawn bodies never become public through relationships.

Run the isolated interactive product using [V10_DEMO.md](../V10_DEMO.md).
All new surface flags remain closed by default. The interactive demo leaves
anonymous preview closed until an explicit source-pinned policy is supplied;
the connected browser fixture exercises that policy after independent approval.

## Integrated parallel work

| Track | Source branch suffix | Verified source commit | Task thread |
|---|---|---|---|
| Requester | v10-requester | 2d20176a23e83774a3cb57001d84b88cc90e8a0c | 6afc8096-82c4-8191-98d8-58fba73eb00c |
| Library | v10-library | e2ddc9509bad77b050bb3a55e22e59fd27b73120 | 6afc808d-03cc-8191-8171-3bfbe0ad201c |
| Source desk | v10-origin-desk | 028170c6a8d40ba8f4bce364ef5310a1a00df2d1 | 6afc807f-d7cc-8191-ad01-1d971f53f019 |
| Recovery | v10-recovery | 213c9df9fe66b44d79f0ef8a42cab960590beb33 | 6afc9ae5-b338-8191-bcff-7654953230ed |
| Delivery desk | v10-delivery-desk | c6d588db02d7c4d9d96a575781afcdac43364e46 | 6afc80af-d6a4-8191-a0ac-08f14e1b300b |

All source branches use prefix `codex/20261117-`. Task URLs were not available
to the integration runtime; identifiers are recorded without inventing links.
Integration-owned worktrees separately delivered the Mufti frame, browser fixture,
demo and recovery failure review. Shared routing and configuration had one writer.

## Verification and retained failures

- Local PostgreSQL 17.12: the first 67-test functional run passed 58 and failed
  nine delivery HTTP tests because their isolated route composition assumed every
  route had a `name`. Library inclusion introduced a URLResolver. The composition
  now preserves resolvers; all nine affected tests passed on recheck.
- Recovery: 22/22 on PostgreSQL 17.12 after review found and fixed a failed final
  READY journal publication. Tests cover disk/write/fsync failures, incomplete
  target quarantine and verified rollback without changing source or backup.
- Connected local browser: one journey passed, Chromium 154, sandbox disabled,
  320/1280 RTL and keyboard interaction, no external requests or page errors.
  The earlier harness selector failure was corrected; it is not counted as a pass.
- The connected journey uses one canonical case through source ambiguity review,
  upload, research, cited multipart answer, human approval, private availability,
  signed part preparation/receipts, independent publication and knowledge preview.
  It stops HTTP before snapshot and restores into a new database/private root.
  A fresh process verifies exact bytes, IDs, relations and permission denials.
  A subsequent focused extension now starts a fresh loopback HTTP server against
  that restored database/private root. Every HTTP request checks `current_database()`
  and the configured storage root against the restored identities, rejecting the
  source identities. It explicitly reattaches scoped synthetic authority and only
  the original public approval/provider verification keys, without signing or
  creating new approvals. Chrome opens the restored Mufti case and requester
  answer, compares exact attachment/audio bytes, plays audio, verifies signed
  delivery and rejects anonymous files, an authenticated out-of-scope principal,
  and private answer/audio after authority revocation. Source HTTP stays stopped.
  The local extended journey passed on PostgreSQL 17.12 with Chromium sandbox
  disabled; the same journey uses Chrome sandbox in CI. The artifact
  `browser/restored-http.json` records target verification and denial results.
- The affected V9 browser journey passed after updating its delivery UI selectors.
- Initial remote compatibility runs exposed two old profile assertions for the
  previous requester handler and middleware name. They now check the explicit
  V10 wrapper, original private guard delegation and closed feature defaults.
  Both assertions plus four composition/privacy tests passed locally (6/6).
  The first V10 workflow also had a YAML scalar parse error; corrected before
  its PG17/18 matrix could run. These historical failures remain in the PR receipt.
- Demo smoke and full offline backup/restore passed: 51 tables and one external
  original. No approvals, signatures or provider outcomes are seeded by the demo.
- Final-head CI runs `infra/dev/v10_verify.py`: 67 focused tests, 22 recovery tests,
  migration drift/system checks on PostgreSQL 17 and 18; Chrome sandbox on PG17.
  Consult the PR's exact-head workflow results for remote pass/fail status.

## Recovery operating limits

Stop application writers, workers, migrations and garbage collection first.
`offline=True` acknowledges that prerequisite; it does not stop other processes.
Backups include PostgreSQL and private originals with independently retained
manifest digest. The archive is trusted, synthetic and unencrypted; never publish
it or upload it as CI evidence. Restore only opens a new owned target, verifies
schema/rows/assets and publishes READY after completion. External identity and
signature authorities must be explicitly reattached in a new application process.

A crash between database creation and durable identity recording requires manual
quarantine. No guessed target deletion is allowed. Persistent filesystem failure
while publishing READY also leaves a non-ready target for verified retry. The
drill does not provide production backup scheduling, online snapshots or cutover.

Gate B **NOT_PASSED**, C/D/E **HOLD**, Phase01 **BLOCKED**, **NOT_DEPLOYED**.
No external messages, production keys/data, unresolved U03 grants or automated
religious approval. The historical engineering reference remains **69% ±8**;
V10 does not assign a new completion estimate or formal acceptance.
