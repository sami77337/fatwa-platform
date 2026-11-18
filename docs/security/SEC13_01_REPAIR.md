# SEC13-01 — independently verified repair at feb4e521

External review `97dd5793e44118d8cd050607717a6acb555f0f1c` is **BLOCKED** on
`38cd137db50cc95ae53fa275b5d90b8274096e5d`. Its unchanged failing tests/report and
historical logs are integrated. The earlier16 green workflows and internal bounded
review do not override the real predicate/fingerprint collision or accepted altered
restoration. Recovery evidence was suspended in the556-point trace; the
repaired-head disposition below permits bounded reinstatement without erasing
that suspension or retroactively crediting the vulnerable head.

Repair product: **`21fd10d3fae9540691f2e29531ddaafa4f60433b`**. Focused runs below
executed the exact product/test content subsequently committed at that SHA, before
the original evidence-only commit. The later external reviewer independently
closed SEC13-01 with **bounded PASS** on
`feb4e521f3c2847403a0e0626ff34da6df7612cc` in report commit
`3008192679e8ac8ba88bc0a82a715fad563adb86`:13/13 per major, including unchanged
original reproductions and four additional adversarial methods. This is the
reviewer's recorded disposition, not closure asserted by the implementer.

## Changed integrity boundary

`platform_recovery.sql_schema` scans the complete raw pg_dump text into tokens and
original byte spans. It replaces the whole-line array regex and `splitlines()`.
Ordinary/doubled-quote strings, E strings with backslash escapes, quoted/Unicode
identifiers, dollar-quoted bodies, line comments (LF/CR/CRLF), and nested block
comments remain opaque. No string decoding, whitespace folding or line-ending
normalization changes their contents. Unterminated opaque tokens fail closed with
a fixed error code, without exposing SQL in the error.

Only a complete recognized varchar-literal-array cast in a real CHECK constraint
or top-level partial-index WHERE expression may be folded to the equivalent
per-element text cast. Literal tokens and their original varchar casts are copied
unchanged. Names, order, predicate operators, columns and uniqueness remain
material. A candidate containing comments is not rewritten. Everything outside
those edits is copied verbatim. Only valid whole-line pg_dump restrict/unrestrict
nonces in ordinary lexical context are omitted, never lookalikes inside opaque
content. This is a narrow pg_dump recognizer, not a general SQL pretty printer or
proof of arbitrary SQL equivalence; unsupported expressions remain exact.

No schema comparison was removed, no fallback accepts the old unsafe fingerprint,
and READY/rollback policy is unchanged. Old synthetic bundles captured with the
former canonicalization may now fail closed: recapture them from the unchanged
owned source under the repaired algorithm; do not rewrite their pinned manifests
or downgrade verification to make them load. No production-bundle migration is
claimed. Existing freshly captured valid encrypted restorations pass on both majors.

The PostgreSQL [SQL-body contract](https://www.postgresql.org/docs/18/sql-createfunction.html)
also supports unquoted BEGIN ATOMIC bodies. A separate reviewer probed the proposed
embedded CREATE INDEX route on fresh PG17.12/18.7; both reject that command in an
unquoted SQL function/procedure body. That probe does not establish general grammar
coverage. Quoted function source preservation is covered by real pg_dump tests.

## Focused execution and retained failures

| Batch, exact contents | PG17.12 | PG18.7 |
| --- | --- | --- |
| External original schema/restore reproductions on38cd137 | FAIL / FAIL | FAIL / FAIL |
| First token-aware repair: external2 + lexical10 + existing recovery5 |17 PASS,5.180s|17 PASS,4.979s|
| Final repair: external2 + lexical11 + existing recovery5 + quarantine2 |20 PASS,7.269s|20 PASS,6.892s|

The final batch follows the small CR-comment handling correction and adds direct
quarantine assertions; it is not an unrelated-suite rerun. Every new real-pg_dump
check uses actual PostgreSQL tools, not a string-only simulated restore. The
external test modules were not weakened or reformatted by the repair.

The new quarantine tests assert the alteration checkpoint executes once, the
journal never contains READY, failure_code is restored_schema_mismatch, original
private bytes remain quarantined, and the source stays FROZEN. A proven fresh
target rolls back to ROLLED_BACK_FILES_PRESERVED. When the target's database nonce
is changed, recovery leaves FAILED/manual quarantine, rejects a further rollback,
and preserves the unknown database. Only the isolated test-cluster teardown later
cleans its own server; the application never guesses deletion.

Ruff, formatting of new code and git whitespace checks pass. Durable outputs and
SHA-256 manifests are in `docs/security/evidence/sec13_01/`. The original external
failures remain under `tests/v13_security_review/evidence/final_v13/`.

Focused reproduction command (choose matching17/18 binaries):

```sh
V12_PG_BIN="$TEST_PG_BIN" FATWA_TEST_PG_BIN="$TEST_PG_BIN" \
  python infra/dev/with_casework_postgres.py --pg-bin "$TEST_PG_BIN" \
  --major 17 --settings config.settings.campaign_review -- \
  python manage.py test tests.v13_security_review.test_final_schema \
  tests.v13_integration_security.test_schema_lexing \
  tests.casework.test_v13_recovery_schema tests.casework.test_v13_schema_quarantine \
  --noinput --verbosity 2
```

## Hosted and independent boundaries

The V13 workflow now includes the independent schema/application/CSP/browser
modules plus lexical/quarantine regressions. The local external microphone attempt
remains **ENVIRONMENT ERROR before page creation**; sandbox was not disabled, and
that historical attempt cannot be turned into PASS. Properly sandboxed hosted
execution is separate evidence and must be attributed to its actual head.

The prior protected CI at38cd137 is historical, security-blocked recovery evidence.
The exact reviewed headfeb4e521 separately passed all16 hosted workflows, including
run44227205996:114 affected tests plus one complete Chrome157 sandboxed connected
restoration journey per PG17.12/18.7. The new recorder method passed there; the
local reviewer's environment error remains NOT_RUN. Final later-head CI is
recorded separately in Draft PR232, not attributed to this earlier execution. Neither this repair note nor its20 passing
checks grants production, acceptance or a new percentage. Gate B NOT_PASSED;
C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No main merge, external send, real data
or keys, U03 grants, GitHub setting changes or unknown-target deletion.
