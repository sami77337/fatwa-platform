# Combined synthetic casework review

`config.settings.campaign_review` is an explicit opt-in profile combining the
private requester intake/status screens and the scoped Mufti team workspace.
`config.campaign_urls` resolves the existing `/casework/`, `/casework/status/`,
`/casework/staff/` and stylesheet paths to these implementations. Both legacy and
new reverse names resolve to the same requester screens. Default/public settings
and `config/urls.py` are unchanged.

The profile inherits `casework_review` gates, loopback/Host guard, request budgets,
CSRF and ownership checks. Web enablement remains explicit; the identity provider
and trusted recovery resolver remain `None`. Configure reviewed synthetic server
objects before exercising staff login. No browser field can supply a provider,
role, recovery identity, signing key or delivery verifier. Use only a freshly
owned disposable PostgreSQL database and fabricated fixtures.

The integrated journey is intake → private receipt/status → authorized staff
clarification → requester followup → draft → return with reason → revised draft
→ Mufti approval. Approval permits preparing a separate exact delivery approval
request; it does not send anything. Requester status never exposes private draft,
answer or review-note text and does not claim receipt or reading. New requester
facts invalidate the approved delivery basis and stale staff forms. Identity,
case scope and auth epoch are rechecked on each action.

Staff login and requester close rotate the shared CSRF secret. In a browser used
for both roles, this invalidates the other role's browser-bound cookie; explicitly
reopen/re-authenticate. Closing a requester browser does not revoke its access
token. Self-service recovery and transcript-to-case binding remain unavailable.

Focused checks (pinned requirements, disposable synthetic PostgreSQL):

```sh
python manage.py test apps.team_workspace.tests tests.casework.test_campaign --settings=config.settings.casework_test --noinput
FATWA_FASTBUILD_BROWSER=/usr/bin/chromium python manage.py test tests.casework.test_campaign_browser --settings=config.settings.casework_test --noinput
```

The tests use one URL configuration for both requester and team, separate browser
contexts, 320/1280 pixel viewports, the actual database and the delivery bridge.
Fixtures never grant production rights. NOT_DEPLOYED / GATES_HOLD.
