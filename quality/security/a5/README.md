# A5 independent public catalog QA

NON_PRODUCTION / NOT_DEPLOYED. Gate B NOT_PASSED; C/D/E HOLD.

Run from this worktree with Node.js 24 (no package installation):

~~~powershell
node quality/security/a5/run.mjs
~~~

The runner writes TAP and JSON evidence only to docs/dev/a5/. It checks the existing
loopback site at http://127.0.0.1:8000. It does not import the host workflow, launch
containers, read credentials, seed data, open a database connection, or alter Git.
No external URL override is supported. The checked-in baseline records the reviewed
HEAD, initial dirty worktree and hashes of 55 implementation/source-contract files.
The runner compares those hashes after testing and reports any ownership drift.

Before bodyless negative-method probes, the local global rejection middleware
must pass a static precondition and the actual /api/v1/status must declare read-only,
sensitive routes disabled, NOT_DEPLOYED and GATES_HOLD. Requests use Node HTTP, so
Host and TRACE are exercised on the wire. They never follow redirects or send
cookies, credentials or request bodies. Maximum one request is in flight.

Keep the evidence categories separate:

- static.test.mjs: nine source inspections; no DB/runtime guarantee.
- adapter.test.mjs: thirteen tests of the real JavaScript adapter using synthetic
  responses. Malicious titles, changed metadata and private-data canaries exist only
  in memory; these are not live HTTP, DOM/browser, or PostgreSQL tests.
- http.test.mjs: nineteen actual HTTP tests. Exhaustively traverses the live tree,
  checks exact public field sets and reconstructs the pinned source mapping digest.
  It compares against the repository source contract; it does not independently
  rehash the original source ZIP or prove database trigger/grant behavior.
- tests/security/test_a5_public.py: seven additional isolated Django SimpleTestCase
  tests, including malicious Arabic source titles rendered by the actual templates,
  explicit public serializers and generic 400/404/503 errors. Database access is
  forbidden. These tests were authored but could not run because Python is absent.

To run only those Django tests where the pinned Python/Django environment exists:

~~~powershell
python -B manage.py test tests/security --settings=config.settings.test
~~~

A5-001/A5-002/A5-003 remain ordinary failing regression tests. Do not convert them
to skips or weaken assertions for a green run. See docs/security-review/A5_FINDINGS.md
for reproduction steps and coordinator actions. Actual browser/keyboard/mobile
acceptance remains NOT_RUN because no connected browser was available. HTML markup
checks and synthetic adapter tests do not substitute for it.
