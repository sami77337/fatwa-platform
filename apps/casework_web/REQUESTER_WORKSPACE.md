# Connected requester workspace (synthetic development)

Base: `e000cdc22c1a0dfd1e0e38eb8fd7cfbfc392487e`, the V6 durable case integration.
The remote branches were inspected before implementation; intake, token recovery,
tracking and followup services already exist and are reused without modification.

## Usable journey

- `/casework/`: save an original synthetic question; show the receipt only after
  durable success, issue the recovery capability once, then open private tracking.
- `/casework/status/`: automatically continue from the receipt, see current status
  and clarification, append a correction/reply without retyping the capability,
  refresh without resubmission, and close/reopen private access.
- A short-lived, signed, CSRF-bound HttpOnly cookie contains the capability. It is
  scoped to the status route, expires after 15 minutes (not extended by refresh),
  and is rechecked against the existing database capability on every operation.
  The database continues to store capability hashes only. This is a local browser
  convenience, not a new identity provider or production session policy.
- Stale revisions retain the submitted text with an explicit retry; a stale tab
  after a case switch cannot submit to the new case. Closing rotates the browser's
  CSRF secret, so other CSRF-bound staff/requester sessions in that same browser
  require re-entry. Separate requester and staff browser profiles are recommended.
- Recovery help points to the existing trusted staff rotation/revocation path.
  Reference-only and self-service recovery remain unavailable. No answers,
  original question text, staff identities or audit rows enter the status page.

## Run / integrate without changing shared files

The implementation is an opt-in URL overlay. No existing file, database model,
service, staff view, URL file, middleware, setting or migration was edited.
The current guard already permits both paths, so its host/loopback checks,
POST/CSRF validation, shared rate budgets and private response headers still apply.

Use an owned synthetic PostgreSQL 17 or 18 database as in the V6 development setup,
with the project's pinned Python 3.13 dependencies. For a fresh local fixture:

```sh
docker run -d --name fatwa-requester-demo \
  -e POSTGRES_USER=wave7_synthetic -e POSTGRES_PASSWORD=synthetic-only \
  -e POSTGRES_DB=wave7_synthetic_requester -p 127.0.0.1:55437:5432 postgres:17
export FATWA_PRODUCTION=0 FATWA_WAVE7_SYNTHETIC_WRITES=1 FATWA_CASEWORK_WEB_ENABLED=1
export PGHOST=127.0.0.1 PGPORT=55437 PGUSER=wave7_synthetic PGPASSWORD=synthetic-only
export PGDATABASE=wave7_synthetic_requester PGTESTDATABASE=test_wave7_synthetic_requester
export DJANGO_SETTINGS_MODULE=apps.casework_web.requester_workspace_settings
python -c 'import django; django.setup(); from apps.intake_workflow.guards import initialize_synthetic_database; initialize_synthetic_database(synthetic_fixtures_only=True)'
python manage.py migrate --noinput
python manage.py runserver 127.0.0.1:8000 --noreload
```

Open `http://127.0.0.1:8000/casework/`. The initial database must be new/owned;
the existing ownership guard rejects unknown databases. No real data is needed.
The staff provider and recovery resolver remain unset until the coordinator
supplies trusted fixture objects using the existing interfaces. The browser test
supplies these through server-side fixtures and exercises the existing staff UI.

For the campaign's combined synthetic profile, select
`ROOT_URLCONF = "apps.casework_web.requester_workspace_urls"` or register the two
adapter views before the old intake/status routes. Keep `CaseworkGuard` and CSRF
middleware. Do not register this overlay in public or production settings.
The integration owner should add `tests.casework.test_requester_workspace` to the
focused database CI labels and `tests.casework.test_requester_workspace_browser`
to the browser check; the shared CI workflow was deliberately left untouched.

## Focused checks

```sh
DJANGO_SETTINGS_MODULE=config.settings.casework_test python manage.py test \
  tests.casework.test_requester_workspace tests.casework.test_http --noinput
DJANGO_SETTINGS_MODULE=config.settings.casework_test python manage.py test \
  tests.casework.test_requester_workspace_browser --noinput
python manage.py check
```

The browser test requires Playwright and Chromium (`FATWA_FASTBUILD_BROWSER` may
select an installed executable). It rejects external requests and covers 360px /
1280px RTL layouts, receipt-to-workspace navigation, the actual staff clarification
form, requester reply, refresh, and closing/reopening. Screenshots default to
`/tmp/fatwa-requester-qa`; no one-time token screen is captured.

Local evidence: PostgreSQL 17.12; 9 new HTTP/database scenarios and 14 existing
HTTP regressions passed (23 total), plus the
connected Chromium 154.0.8037.57 journey. The executor's Chromium sandbox helper
was unavailable; the synthetic-only browser run used `FATWA_BROWSER_SANDBOX=0`
inside the isolated executor, with external page requests blocked. Normal test
execution keeps the browser sandbox enabled. Product access controls are unchanged.

No external delivery, reading proof, self-service recovery, production identity or
gate acceptance is claimed. `NOT_DEPLOYED / GATES_HOLD`.
