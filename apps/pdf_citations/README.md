# Private PDF page citations

Scoped staff can propose, preview, confirm, correct and withdraw page locators
on existing immutable private PDF originals. Physical page counts come from the
existing parser; printed page labels require an explicit human assertion. The
answer/source versions and SHA256 remain pinned, and history is append-only.

See [CONTRACT.md](CONTRACT.md) for API, exact rights, required approval/use hooks,
route admission and the audio-context extension; see [EVIDENCE.md](EVIDENCE.md)
for test results and limitations. The app is closed by default and has no public
or requester endpoint. Shared integration is intentionally not changed here.

Focused synthetic PostgreSQL test composition:

```sh
.local/venv/bin/python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.pdf_citations.settings -- \
  .local/venv/bin/python manage.py test \
  apps.pdf_citations.tests apps.timed_citations.test_preview_context \
  apps.timed_citations.tests.TimedTests.test_native_http_csrf_scope_player_and_private_bytes
```

Use a fresh owned cluster for the same labels on PostgreSQL 18. Browser labels:
`apps.pdf_citations.browser_tests`, `apps.timed_citations.browser_tests`.
Browser tests default to Chromium sandbox enabled; local exceptions, if required
by the runner, must remain explicitly attributed as functional-only evidence.
The harness may observe Chrome's PDF navigation response; assertions
on server byte response headers use an independent authenticated HTTP request.
No application CSP or authorization is relaxed for a browser test.
