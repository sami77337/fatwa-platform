# Local E2/E4 composition evidence

Scope: E2-owned adapter only, relative to published E2 b55c4596506aafd3c3d5c3a3c0fee1450fc2d2c2.
Actual E4 dependency identity is in E4_ADAPTATION_PLAN.md. No E4/shared files are
committed in E2. The temp test checkout reports b55 with DIRTY overlays, not an
official integrated committed SHA. This evidence supersedes older adapter plans.

## Regression and final results

Before changes the new four-method regression module ran four methods:
2 failures and 3 subtest errors (unexpected mode keyword in three mode cases;
unified-enabled page404 instead of200; invalid-mode404 instead of400). Current
reference-state case already passed. `/tmp/w7-e2-adapter-red17.log` is retained.
One initial broad namespace test label failed collection (module.__file__ None);
explicit actual module labels below corrected collection. It was not a test pass.

Final composite commands executed with Python3.13.5 from the existing pinned
uv venv `/tmp/fatwa-wave7-e2-venv`; Node24.19.0; same hosted Linux environment.
The resource helper copied the existing ownership-verifying helper and changed
only its checkout to `/tmp/fatwa-w7-e2-adapter` and reads environment flag to1.
Each PG service was a new private synthetic tmpfs container from the same official
17/18-bookworm images already recorded in EVIDENCE.md. Role wave7_synthetic,
literal127.0.0.1 random ports, unique wave7_synthetic_e2_{17,18}_* base and matching
test_ names, exact container-ID/label verification before each command and cleanup.
No owner data, source archive or inherited credential target. Shared guard, test
runner and migrations were unchanged; only their own marked test DB was created.

```sh
/usr/bin/python3.13 /tmp/w7-e2-adapter-postgres.py start <17|18>
# The helper executes subsequent Python arguments using the pinned 3.13 venv:
/usr/bin/python3.13 /tmp/w7-e2-adapter-postgres.py run <17|18> -c 'import django; django.setup(); from apps.intake_workflow.guards import initialize_synthetic_database; print(initialize_synthetic_database(synthetic_fixtures_only=True))'
/usr/bin/python3.13 /tmp/w7-e2-adapter-postgres.py run <17|18> manage.py migrate --noinput --settings=config.settings.wave7_test
/usr/bin/python3.13 /tmp/w7-e2-adapter-postgres.py run <17|18> manage.py test tests.wave7_foundation.test_database tests.wave7_foundation.test_review_regressions tests.wave7_foundation.test_lossless_db tests.editorial_demo.test_wave7_review_db tests.editorial_demo.test_wave7_read_db tests.editorial_demo.test_wave7_e4_adapter_db tests.integration.ui.wave7_workflow_reads_db --noinput --settings=config.settings.wave7_test
PGPORT=1 /tmp/fatwa-wave7-e2-venv/bin/python manage.py test tests.editorial_demo.test_preview tests.editorial_demo.test_pipeline_preview tests.editorial_demo.test_worklist tests.editorial_demo.test_synthetic_batch tests.editorial_demo.test_review_fixes tests.editorial_demo.test_wave7_review_off tests.integration.api.test_wave7_workflow_reads --noinput --settings=config.settings.test
/tmp/fatwa-wave7-e2-venv/bin/python -m unittest tests.wave7_foundation.test_contracts tests.wave7_foundation.test_guard_config tests.wave7_foundation.test_lossless -v
/tmp/fatwa-wave7-e2-venv/bin/python tools/dev/wave4_qa.py --wave3 --json /tmp/w7-e2-adapter-wave4.json
git diff --check
```

- PG17 actual170011: **80 methods PASS**, 0 failures/errors/skips, 10.314s.
- PG18 actual180006: **80 methods PASS**, 0 failures/errors/skips, 10.158s.
- Each80 = foundation34 + unchanged review16 + persisted read12 + adapter8 + E4DB10.
- Port1 default-off/legacy and E4 no-DB: **75 PASS**, 0 failures/errors/skips,0.803s.
- Foundation pure: **25 PASS**, 0 failures/errors/skips,13.801s.
- Existing D6 + C6 dispatcher: PASS. Its full importer84 ran80 passed/4 source
  skips; no uncollected importer modules. Four skips are missing trusted archive:
  real mapping checksum, owner CSV, owner JSONL, owner nested JSON. Real source
  acceptance remains NOT_RUN. Counts overlap earlier checks; do not sum reruns.
- Actual E2 list SELECT/SHOW counts **[18,18]** for page sizes1 and8 on each PG;
  no per-item detail query, no SQL write. Actual E4 measured literal8 queries,
  normalized9 queries (synthetic timings only; no owner-data extrapolation).

Actual mode tests compare UUID/order/count directly with E4 API and SSR context
without replacing production readers. Additional tests exercise mode/state return
and reload; current UNVERIFIED→VERIFIED→MISMATCHED citation; unified flags/env404
before SQL; invalid mode/offset400 before SQL; actual normalized scope400; actual
shared read-guard failure503 before SQL; external ID not a question-search alias.
Original source/numeric/null, restart, UUID isolation, escaped events/citations,
bounded history and write/replay/concurrency/rollback/CLI tests remain passing.

Both exact owned containers were verified and removed with
`/usr/bin/python3.13 /tmp/w7-e2-adapter-postgres.py stop <17|18>` after tests.
No other service or image was removed. Dispatcher summary (overlapping suites):

```json
{
  "node_version": {
    "status": "PASS",
    "counts": null,
    "node_registered": []
  },
  "django": {
    "status": "PASS",
    "counts": null,
    "node_registered": []
  },
  "D1.python.0": {
    "status": "PASS",
    "counts": {
      "run": 41
    },
    "node_registered": []
  },
  "D2.django.0": {
    "status": "PASS",
    "counts": {
      "run": 16,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "D2.django.1": {
    "status": "PASS",
    "counts": {
      "run": 9,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "D2.django.2": {
    "status": "PASS",
    "counts": {
      "run": 19,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "D2.django.3": {
    "status": "PASS",
    "counts": {
      "run": 11,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "D2.django.4": {
    "status": "PASS",
    "counts": {
      "run": 6,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "D3.python.0": {
    "status": "PASS",
    "counts": {
      "run": 50
    },
    "node_registered": []
  },
  "D4.django.0": {
    "status": "PASS",
    "counts": {
      "run": 4,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "D4.django.1": {
    "status": "PASS",
    "counts": {
      "run": 8,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "D4.node": {
    "status": "PASS",
    "counts": null,
    "node_registered": [
      "49"
    ]
  },
  "D5.django.0": {
    "status": "PASS",
    "counts": {
      "run": 18,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0
    },
    "node_registered": []
  },
  "wave3": {
    "status": "PASS",
    "counts": {
      "run": 84
    },
    "node_registered": []
  }
}
```

## Logs and limits

Local log SHA256s (logs are retained in /tmp; no source/DSN/reason secrets):

```json
{
  "w7-e2-adapter-red17.log": "a5193110ca8f988ec1ecf7d562655bd2ee5d651c2a32a420008de325091a0958",
  "w7-e2-adapter-full17.log": "32a95827b984122276ed1e509d294a45147cc652417c308d80466cfecd07df1a",
  "w7-e2-adapter-full18.log": "551464977d031cfc0532e71a818876163a824cd810ec20986f930a9ece2ee951",
  "w7-e2-adapter-pure-full.log": "8eb95770daf27a857b3d4be693594ae7a99585f8dd38d19e8ca829063152acfe",
  "w7-e2-adapter-foundation-pure.log": "a3f72b1b62cdf03efb3eb74b1b867cabdcdb857a5dd3636c49527c89525b594a",
  "w7-e2-adapter-wave4.json": "90bdff1dc8da7d28d8075f74607a207d054914c585f80c206a3984834143d56e"
}
```

E2 transition/CLI files unchanged except the read portion of review.py. Shared
settings/URLs, E4 files, models/migrations/guards/fixtures and root CI untouched in
the producer commit. No push/PR metadata/issue comment/publication under current
hold. Existing PR61 and b55 stay unchanged remotely. New head has no CI run.
NOT_RUN: final coordinator assembled-SHA matrix, Windows, real browser/E6,
new independent review and real-source acceptance. NOT_DEPLOYED / GATES_HOLD /
USAGE_NOT_OBSERVED. No main write/merge or security/sandbox changes occurred.
