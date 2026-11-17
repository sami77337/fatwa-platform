# V6 durable casework integration — 17 November 2026

This development branch starts at PR #208, `23839110af15baf09ed80b1002a328021cea5e31`.
It preserves the original branch and `main`. No deployment, real-channel sending,
real requester intake, historical permission grant or owner acceptance occurs.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.

## Recovery decisions

The [dependency receipt](V6_PR_DEPENDENCIES_20261117.json) records the base and head
of all 58 PRs from #151 through #208. Ancestry alone does not establish feature
presence. The following decisions also compare the actual relevant files.

| PR / source head | Decision and bounded reason |
|---|---|
| #183 `99cd56ea70195526e8b02f1aced0086ae6f343f8` | Recover staff query aliases and tests. The source excludes standalone دون; its PR description is stale. |
| #185 `0877d2688fc3f83e67d0d60625e96b429d1cda0f` | Recover editorial recall/evaluation. Preserve literal matching, constrain alias word boundaries, rank literal results first and explain synonym matches. Never rewrite source text. |
| #173 `b9a815f91649b6cd40b3e3adc2e3cfbe2d1a7238` | Recover six absent public-page metadata files/changes; trusted HTTPS origin only, no query-derived canonical links. |
| #168 `01dd475f2913df2f2419ef59fb2efea905ae6410` | Deferred separate recovery: its read-only reference-catalog checker requires the absent 15-file #154 subtree. It adds no case model or migration, is not a dependency of this casework journey, and its old branch-specific CI cannot be copied as evidence for this branch. |
| #170 `dd0287507cc3587cd7e4b1984b5630907eb12d7b` | HOLD: verifier needs original scope/evidence inputs (`542.docx`, `requirements.jsonl`, `PRODUCT_SPEC.txt`, reconciliation manifest and the two semantic mapping JSON files). The current scope workbook is not a byte-identical substitute. No fabricated acceptance. |

## Operational contract

`apps.casework` owns durable UUID case identities, distinct random public FT
references, immutable source/evidence/answer/event rows and explicit current
pointers. PostgreSQL transactions, row/advisory locks, constraints and reversible
integrity triggers enforce linkage, idempotency and concurrent updates. New facts
append evidence and clear the prior approval. Only a trusted, active, case-scoped
MUFTI can author or decide substantive answers.

The existing tracking row is a one-to-one capability binding, not another case
state machine. Legacy read and mutation APIs reject bound or reserved `case:`
identities even when the old Django settings omit the new app. Canonical requester
reads validate the operational history. Both new and legacy token reads recheck
revocation after waiting for their relevant lock.

`apps.casework_web` connects website intake, private status/followup and trusted
staff review using native POST forms, CSRF, no-store/noindex, strict cookies and
shared PostgreSQL request budgets. The review profile is disabled by default and
loopback only. Public/production settings do not register the app or its routes.
Staff identity and recovery must be explicitly supplied by trusted server objects;
browser-selected roles or requester IDs cannot configure them.

## Reproduction and evidence boundary

Use Python 3.13 with the exact `requirements.txt` pins. On a disposable local
PostgreSQL installation, the wrapper creates a new scratch cluster and never
contacts an existing database:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin --major 17 -- python manage.py test tests.casework.test_core tests.casework.test_http tests.casework.test_adversarial tests.casework.test_tracking_bridge --noinput --verbosity=2
```

Repeat the same distinct test set on major 18; it is compatibility evidence, not
twice the feature count. `.github/workflows/v6-casework.yml` pins checkout to the
PR head and records SHA, PostgreSQL major, actual test results and Chrome artifacts.
The browser command is `python tools/dev/casework_browser.py` against the same
owned synthetic database. It exercises mobile and desktop, two cases, scoped staff
work, clarification, approval, token rotation/revocation and data isolation.
Final result counts and CI URLs belong to the Draft PR, so updating the receipt
does not silently change the tested code revision.

## Known limits and independent observations

- New case approvals are not wired to signed provider delivery evidence. The
  canonical status returns `delivery_verified=False`, `read_confirmed=False`;
  approval is not delivery or answer availability. Existing #207 provider evidence
  remains separate and must not be used as acceptance of this missing binding.
- This is a text-only synthetic journey. Production identity/recovery/KMS,
  permission-policy acceptance, channels and media are still out of this release
  receipt. The inherited 47% maturity estimate is not recalculated.
- Local Chromium startup is blocked by the executor's Unix-socket restriction;
  local browser execution is NOT_RUN. Real Chrome must pass in GitHub CI before
  browser integration can be called verified.
- Read-only GitHub observations on 17 November: repository visibility `public`,
  `main.protected=false`, protection `enabled=false`, and rulesets `[]`. No settings
  changed. These observations are not evidence of secret exposure.
