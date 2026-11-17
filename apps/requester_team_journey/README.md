Integration note: `apps.requester_team_journey.settings` now aliases
`config.settings.campaign_review`; both names use `config.campaign_urls`,
the same dispatcher, migrations, guards and template overlays, including the
case-scoped internal update inbox. The panel cookie may also contain `updates`;
it remains an unauthoritative preference. The older
integration adapter reexports this dispatcher. There is one implementation.

# Combined requester / team journey — local synthetic profile

This closes the routing gap between the new team workspace, private requester
workspace and requester access-review queue. The team desk remains the default;
its new navigation button opens access reviews, review actions return to that
queue, opening a case uses the current team editor, and a button returns to the
case list. Intake, clarification, reply, human draft/review and trusted access
rotation now work in one profile.

## Dependencies and ownership

The isolated branch includes upstream commits unchanged:

- Campaign integration `e7fd0d2` (including requester workspace `59813f5`).
- Access-review slice `29f1bd5`.
- Team workspace `8828836` (including its pending-clarification write guard).

Only `apps/requester_team_journey/**` is new implementation. Existing team,
requester, casework, identity, migrations, shared URLs/settings and CI files are
not edited by this composition. Local dependency merge commits do not merge
anything into `main` or update the campaign branch.

## Integrate / run

After the dependencies above are present, the composition commit can be
cherry-picked by itself. Select:

```sh
export DJANGO_SETTINGS_MODULE=apps.requester_team_journey.settings
python manage.py migrate --noinput
python manage.py runserver 127.0.0.1:8000 --noreload
```

Use the owned synthetic PostgreSQL setup and environment flags documented in
`apps/casework_web/REQUESTER_WORKSPACE.md`. `FATWA_CASEWORK_WEB_ENABLED=1`,
`FATWA_WAVE7_SYNTHETIC_WRITES=1`, and `FATWA_PRODUCTION=0` remain required.
Open `/casework/` for intake, `/casework/status/` for the requester workspace,
and `/casework/staff/` for the team. No new database schema is introduced here;
the dependency's access-review migration is still required.

The profile inherits all guards and trusted-provider requirements. A deployment
must not infer identities or recovery verification from this profile. The browser
test supplies synthetic server-side provider/resolver fixtures; otherwise the
existing trusted staff provider and recovery resolver must be configured by the
integration owner. Neither self-service recovery nor real delivery is added.

## Implementation seam

`urls.py` composes the existing paths directly: requester intake/status adapters,
new team workspace for case actions, access-review staff handler for `access_*`
actions, and the existing authentication/followup routes. The original legacy
staff mutation view is not used as a fallback, preserving the team's extra
pending-clarification guard.

`fatwa_team_panel` stores only `cases` or `access`, for 15 minutes, under the staff
path. It is an HttpOnly/SameSite preference, **not an authorization credential**;
both handlers still validate current identity and case scope on every request.
Unknown values select the normal desk. POST+CSRF controls navigation. Refresh
after review mutations follows the existing 303 redirect back into the review
queue without replaying the mutation.

Two tiny same-name Django template overlays add navigation via `block.super`.
They inherit the original templates rather than copying them. Only this opt-in
profile prepends their template directory; other profiles are unaffected.

## Focused evidence

```sh
python manage.py test apps.requester_team_journey.tests \
  apps.requester_team_journey.browser_tests --noinput
python manage.py check
ruff check apps/requester_team_journey
```

Four composition tests and one full real-browser journey passed on PostgreSQL
17.12 / Chromium 154.0.8037.57. The browser traversed intake → team clarification
→ requester reply → human draft/approval → access-review request → scoped review
queue → trusted fixture rotation → old access denied → closure → return to team.
The requester never saw answer text, and the profile retained the team's guard
against drafting while clarification is pending. Mobile requester 360px and team
1280px RTL had no overflow, page errors or external requests.

As in prior local runs, this executor required `FATWA_BROWSER_SANDBOX=0` with
writable XDG directories under `/tmp`; the test defaults to Chromium's sandbox
enabled. Screenshots are in `/tmp/fatwa-requester-team-qa` and exclude issuance
screens and raw tokens. Ruff and Django system checks passed. No PG18 or hosted
CI success is claimed. Add only the two focused labels above to combined CI.

`NOT_DEPLOYED / GATES_HOLD`. No real data, external sends, public routing or main merge.
