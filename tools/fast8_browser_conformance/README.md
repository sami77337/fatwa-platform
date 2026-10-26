# FAST8 guarded operator browser conformance

This lane adds executable QA only, based on FAST7 CI integration
`92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134). It uses the existing
Django routes, fixed synthetic domain services and `ProtectedBrowser` from
`tests/acceptance/fastbuild/startup.mjs`, including its Windows job containment,
private temporary profile, protected CDP endpoint validation and cleanup.
There are no application patches, URL mounts, dependencies, shared CI changes,
source archives, database creation/seeding/migrations, or security flag changes.

Run from the repository root with the installed Python 3.13 / Node 24:

```text
python manage.py test tests.fast8_browser_conformance.test_conformance --settings=config.settings.test --verbosity=2
python -m tools.fast8_browser_conformance.run
```

The first command runs the new HTTP guard and harness tests, including the Node
negative cases and actual Chrome. It creates no test database. Use the full
module name: discovery by package label encounters this repository's namespace
`tests` package issue. The standalone Node regressions can also be run as:

```text
node --test --test-reporter=tap tests/fast8_browser_conformance/policy.test.mjs
```

The second command prints machine-readable evidence with actual Git HEAD, dirty
owned-path status, fixture digest, individual checks, browser/catalog status and
cleanup result. Exit codes are **0 PASS, 1 FAIL, 2 NOT_RUN**. Browser PASS with
catalog NOT_RUN aggregates to NOT_RUN, never full acceptance. The Python browser
test asserts that distinction. Missing Chrome/Node is NOT_RUN; application
assertions, deadline overruns and cleanup failures fail. No raw Chrome stderr is
published. Set `FATWA_FASTBUILD_BROWSER` to an existing Chrome executable when
the standard platform path is unavailable; no additional flags are accepted.

The 17 DB-free browser checks cover:

- 1280/375/320 actual viewport widths, Arabic RTL, overflow with details open,
  skip-link focus, Enter activation and keyboard search submission.
- Existing queue source/revision links into workbench; historical search hits
  into the exact selected revision; search/research/triage/workbench links;
  search/export/packet links. Navigation follows real links, including fragments.
- Intake source and input hashes, exact selected revision, all revision fields
  and reference pins, original Unicode/CRLF in search and JSON, and bytes/hashes
  of all four existing export files. Source hashes are not revision text hashes.
- Missing cases in queue/research/workbench and nonexistent revisions, with
  keyboard recovery and no substituted snapshot.
- CDP denial of POST/PUT/PATCH/DELETE and a foreign-origin navigation, with
  actual interception events required as evidence. Unknown routes, persisted
  workflow-audit, media and nonlocal requests are outside the allowlist.
- Console/runtime errors and unexpected subresource HTTP errors fail the run.

The Python tests additionally verify all four unsafe methods on eight existing
routes, foreign Host/peer denial, production closure and private read responses.
HTTP Origin alone is not a server authorization check in this application;
foreign network origins are denied by the CDP guard. The harness never sends
its deliberately unsafe browser probes to Django.

## Existing synthetic PostgreSQL only

Without explicitly supplied configuration the source catalog portion is
`NOT_RUN / SYNTHETIC_POSTGRES_NOT_SUPPLIED`. The DB-free journey uses research
`history`, whose unresolved references require no catalog query. Accidental DB
connections are forbidden; no catalog lookup is mocked during browser acceptance.

For an already provisioned, exclusively synthetic PostgreSQL 17/18 database,
the coordinator may run the CLI with `FAST8_EXISTING_SYNTHETIC_PG=1` and the
existing Wave7 settings/environment. `require_owned_database` remains the
authority over loopback, database role/name, ownership and synthetic scope. Its
existing opt-in requirements must already be satisfied. This tool does not set
write flags, claim a database, create tables, migrate, seed or repair it.

Preflight runs in a child with a 15-second bound. Counts must be exactly one
work, one edition and three headings before any catalog text is retrieved.
Public metadata and every node must match the existing fixed seed:
`wave7-synthetic-toc`, edition 7001, rows 1–3, archive SHA `a` repeated 64 times,
input SHA `b` repeated 64 times. Extra rows/editions or changed identity fail;
missing configuration, ownership or availability is NOT_RUN. Only then can the
browser follow research → source links at all three widths and compare displayed
and API node/edition identity. This optional path has **not been run locally**.
Use a quiescent owned synthetic database; concurrent fixture changes invalidate
the preflight evidence. Persisted workflow/event acceptance is outside this lane.

## Local validation and review

Python 3.13 / Django 5.2.18 / Node 24.16.0 / actual Windows Chrome:
13 Python tests passed, zero skips; the included Node wrapper ran 20 tests,
zero skips; actual browser ran 17 checks with cleanup PASS. These are nested
counts, not 50 independent acceptance tests. PostgreSQL/source acceptance is
NOT_RUN. Existing synthetic export report SHA256:
`17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9`.

Initial package-label discovery failed; the full module command above works.
The first wrapper run hit Windows cp1256 encoding for Node's pretty checkmark;
the TAP reporter corrected it. A transient test-edit syntax error was corrected
before the final passing run. No application assertion or browser failure was
skipped or weakened. Ruff check/format passed on the owned Python files.

One independent review completed. Its five findings (actual mobile width,
required htmx asset, persisted-route exclusion, asset/console failure detection,
exclusive catalog identity) were fixed and verified within that same review.
Shared B6/C6/D6 workflows are unchanged and do not register this new suite;
their actual final-SHA statuses are reported in the Draft PR, independently of
the local conformance evidence. The coordinator can invoke the focused command
above when integrating.

NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. No production or scholarly acceptance is implied.
