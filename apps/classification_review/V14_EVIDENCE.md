# V14 classification editorial simulation — executed evidence

Base remote verified before implementation and again before handoff:
`refs/pull/232/head = 1f08cbb7166f70ec340c495da33ccfc1eda9534e`.
V13 remote classification branch remains
`fee124fe00920a83ca790f0e10a6f4ab9812b199`.

The final service and browser checks ran against the product/test working tree;
only documentation and copied evidence were added afterwards, before commit.
These are local results, not exact-head hosted CI or independent security approval.
All materials, credentials, rights grants, policies, identities and cases are
synthetic. No externally supplied source content or real credentials were used.

Environment: Python3.13.5 / Django5.2.18 / psycopg3.3.6. Fresh temporary
Docker PostgreSQL17.12 and18.7, ephemeral loopback-only ports, tmpfs data,
`wave7_synthetic` role, explicit ownership initialization and both new migrations.
The containers were stopped/removed after checks. Prior V13 artifacts are preserved.

| Check | Executed result |
|---|---|
| V14 service18 + native HTTP3 + affected V13 service13 + shared wiring3 | PG17 **37/37 PASS**,41.384s |
| Same focused selection | PG18 **37/37 PASS**,41.878s |
| Native RTL prepare → review → independent publication → redacted audit | PG17 **1/1 PASS**,5.394s |
| Browser | Chromium154.0.8037.57, explicit sandbox=False |
| Widths/focus/network | 320/1280, RTL, no overflow, keyboard focus, zero external requests/page errors |
| Django system check / migration drift | no issues / no changes detected |
| Ruff / formatting / git whitespace | PASS |

V14 tests cover exact copy and category provenance without automatic publishing;
manual REVIEW then independent APPROVE; default-off/absent/wrong-version policies;
strict literal confirmation and synthetic/production checks; unapproved/rejected/
withdrawn/corrected classification refusal; direct canonical action bypass denial;
changed knowledge/publication/answer/evidence; expiry/revocation of real registered
source rights; late policy/identity/rights callbacks with rollback/no response leak;
case-scope/cross-ID rejection; immutable binding; concurrent preparation (one
candidate) and publication approval (one decision); freeze denial; strict native
forms/CSRF/forged actor rejection and private error behavior.

The browser ran with source rights enforced and maintenance admission required,
against the integrated dispatcher. It used native confirmation controls for each
step and a separate authenticated publisher. The setup-only entry form supplied
the documented existing classification desk action, without bypassing CSRF or
identity. Screenshots `evidence/v14/candidate-320.png` and `published-1280.png`
were visually inspected. The editor cannot see the independent publication approval
button. Book source metadata is labelled as TOC, never book text.

## Reproduction

With executor-provided PG17/18 binaries and repository dependencies:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.classification_review.settings -- \
  python manage.py test apps.classification_review.editorial_tests \
  apps.classification_review.editorial_http_tests apps.classification_review.tests \
  tests.casework.test_v13_classification_wiring

python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.classification_review.settings -- \
  python manage.py test apps.classification_review.editorial_browser_tests
```

Repeat focused services using major18. Browser requires Playwright1.58.0 and
`/usr/bin/chromium`. The harness defaults to sandbox enabled; local execution used
`FATWA_TEST_BROWSER_NO_SANDBOX=1` with temporary writable XDG directories. The known
executor SUID sandbox restriction from V13 remains; no new protected-browser PASS
is asserted. Do not convert this local workaround into the integrator's CI default.

## Historical attempts, not hidden

- Migration generation warned about intentionally unreachable port1; the migrations
  subsequently applied on fresh owned PG17/18 clusters, and drift checks passed.
- First V14 PG17 service attempt:12/14 pass, two test errors. The test expected a
  domain error in production mode, but mandatory maintenance admission correctly
  denied earlier; expectation now matches MaintenanceUnavailable. The second used
  nonexistent `maintenance.freeze`; it now calls the existing `maintenance.enter`.
  No guard was weakened. Next affected selection27/27 passed before added scenarios.
- Added service18 passed; three new HTTP tests failed at fixture login because the
  synthetic credentials were shorter than the existing32-character minimum. Test
  credentials were corrected; the real identity requirement was unchanged.
- The final37-test runs above include the added cases and permission-aware native
  UI, plus the unchanged affected V13 checks. Counts do not add earlier repeats.
- Pre-handoff review added explicit service requirements for source-rights-enabled,
  source-rights-enforced and maintenance-required flags, so an operator cannot
  activate this drill in a legacy composition by enabling its flag alone. The
  negative configuration tests cover all three. Earlier37/37 runs took42.626s
  (PG17) and42.072s (PG18); the table records the subsequent strict-composition runs.
- The browser initially passed in5.364s and was rerun after this guard hardening.
  No production or external site was visited, no data sent, and no unrestricted
  publication policy was configured.

No concrete security bypass was observed; no independent review PASS is claimed.
Remaining: integrator's combined-head checks, exact schema/recovery round-trip for
new table/guards, sandbox-enabled Chrome, and independent security review. If such
review finds a defect, stop its affected path pending repair and independent retest.
Product policy approval, real-user permission, main merge and deployment remain
blocked. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No new estimate.
