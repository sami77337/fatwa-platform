# Combined synthetic casework review

`config.settings.campaign_review` is an explicit opt-in profile combining the
private requester intake/status screens and the scoped Mufti team workspace.
It also registers the optional `requester_access_review` app and its initial
migration. Existing access is required to request review; the staff queue opens
from the team screen and returns to the same team editor. Acknowledging a request
does not revoke or replace its token. Closing requires prior trusted revocation.
`config.campaign_urls` resolves the existing `/casework/`, `/casework/status/`,
`/casework/staff/` and stylesheet paths to these implementations. Both legacy and
new reverse names resolve to the same requester screens. Default/public settings
and `config/urls.py` are unchanged.

`apps.requester_team_journey.settings` is a compatibility name for the same
canonical settings and URL composition. The shared dispatcher supports cases,
access reviews and the internal updates inbox. Its short-lived panel cookie
contains only a display preference; every destination rechecks staff authority.
The `team_updates` app/migration records an immutable explicit seen marker per
provider, subject and event. Opening a case never marks its updates seen, and a
seen marker never approves evidence, a ruling, delivery or requester reading.

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
python manage.py test apps.team_workspace.tests apps.requester_access_review.tests tests.casework.test_campaign tests.casework.test_campaign_access --settings=config.settings.campaign_review --noinput
FATWA_FASTBUILD_BROWSER=/usr/bin/chromium python manage.py test tests.casework.test_campaign_browser --settings=config.settings.campaign_review --noinput
```

The tests use one URL configuration for both requester and team, separate browser
contexts, 320/1280 pixel viewports, the actual database and the delivery bridge.
Fixtures never grant production rights. NOT_DEPLOYED / GATES_HOLD.
