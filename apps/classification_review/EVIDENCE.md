# V13 P1-D executed checks

Base remote verified before changes and before delivery:
`refs/pull/231/head = 5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`.
Only new `apps/classification_review/**` files are delivered. Test evidence was
collected on the final product/test working tree, then documentation and artifacts
were added before commit; it is not a claim of exact-head hosted CI execution.

Python3.13.5, Django5.2.18, psycopg3.3.6, Playwright1.58.0.
Fresh temporary loopback-only Docker PostgreSQL17.12 and18.7 clusters, role
`wave7_synthetic`, database `wave7_synthetic_v13classification`, synthetic ownership
initialized through the existing guard, both new migrations applied. No installed
or production database was contacted. Docker images:

- `postgres:17`: sha256:0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac
- `postgres:18`: sha256:2ea8630df176ad090ec92136dee850397c5af8781e4bcf2e4162593691c61bbc

The development-only trust authentication was bound to ephemeral loopback ports
inside this executor and used no real passwords. Both temporary containers were
removed after checks.

| Check | Executed result |
|---|---|
| Focused service, PostgreSQL integrity, race and HTTP/CSRF | PG17 **13/13 PASS**, 8.805s |
| Same focused tests | PG18 **13/13 PASS**, 8.782s |
| Native browser proposal → independent reviewer → withdrawal | PG17 **1/1 PASS**, 5.981s |
| Chromium | 154.0.8037.57, explicit **sandbox=False** |
| RTL viewports / focus / horizontal overflow | 320 and1280; keyboard focus observed; no overflow |
| Browser requests / page errors | zero external requests, zero page errors |
| Django system check | no issues |
| Migration drift | no changes detected |
| Ruff check / formatting / git whitespace | PASS |

The 13 tests cover: proposal pending until independent human decision; canonical
publication and knowledge stores unchanged; default-deny authority and revoked
identity/scope/role; reject/correct/withdraw lifecycle; changed knowledge source;
changed source fingerprint and publication version; text redaction after source
rights loss; simultaneous APPROVE/REJECT on separate real connections (one wins,
one conflict); immutable DB rows and independent/exclusive decisions; native HTTP,
CSRF, extra-authority-field rejection and private errors; feature-off/no-confirm/
unapproved source denial; late authority revocation rolling back an inserted
decision; cross-publication IDs; real source-rights expiry/revocation with safe
redacted audit and post-revocation withdrawal.

The final browser screenshots in `evidence/rtl-320.png` and `rtl-1280.png` were
visually inspected. The proposing human sees correction/proposal controls but no
self-approval control. The independent reviewer uses real native forms; the test
only injects the documented entry form because shared navigation is outside lane
ownership. No body text or fabricated quote is presented as book622 content.

## Historical attempts retained

- Initial Python environment setup hit the executor's read-only UV cache. Retried
  with a temporary cache and isolated Python3.13 environment; no project deps changed.
- Migration generation warned about deliberately unreachable port1. Real owned
  PG17/18 migrations subsequently succeeded; the warning is not a migration PASS.
- First test invocation before explicit database bootstrap was denied with
  `DATABASE_OWNERSHIP_REQUIRED`. No guard was relaxed; the fresh empty database was
  then initialized using `initialize_synthetic_database` and migrated normally.
- First nine-test run: eight pass, one test expected404 after complete staff scope
  removal while the existing identity guard correctly returned403. The assertion
  was corrected; authorization behavior was unchanged.
- Earlier 12-test passes and single added real-rights passes on both PostgreSQL
  majors preceded the final permission-aware UI changes. The table reports the
  final13-test runs, not a sum of repeated executions.
- Sandbox-enabled Chromium failed at launch because the executor's SUID sandbox
  helper lacked required ownership/mode. No browser journey ran in that attempt.
  Explicit local `sandbox=False` plus writable XDG paths allowed the synthetic
  journey. Sandbox-enabled browser proof remains outstanding for integration.
- The earlier browser pass was repeated only after the permission-aware UI change;
  the table and screenshots report the final run.

No security bypass was observed, and no independent security PASS is claimed.
No hosted CI, full integrated campaign, PG18 browser, strict recovery drill, real
source licence, real data, production operation, acceptance change or new percentage
was tested/claimed. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
