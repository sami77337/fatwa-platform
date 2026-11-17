# Campaign compatibility review — 2026-11-17

Result: the canonical composition preserves the reviewed isolation and state
contracts for #219 (inbox), #212 (team editor), and the requester journey. No
additional runtime repair is required by these checks. This review adds seven
regression tests and a PostgreSQL 17/18 workflow, without modifying runtime code.

## Exact inputs

- #212: `8828836e644c8c24db871774ab516d7d6f464386`.
- #219: `b0e345f6292e3ce32c61a41a6886fdfe24690dac`.
- Initial integrated review: `1109af0223edd20d2f57098922e7950d470226f0`.
- Final tested campaign base: `622921deb25af69e1d762c86963fd08ed6e861fb`,
  including the subsequently integrated delivery desk.
- Independent branch: `codex/20261117-review-team-updates-compat`.

## Integration finding and existing repair

A temporary direct inbox mount reproduced an unsafe composition: a forged draft
while awaiting requester clarification returned HTTP 200 through the legacy
case handler instead of #212's expected HTTP 409. This was a wiring problem in
that temporary composition, not a failure of the final campaign dispatcher.

The integration owner already corrected the routing in `1109af0`. Keep
`config.settings.campaign_review`, `config.campaign_urls`, and the canonical
`apps.requester_team_journey.views.staff` dispatcher. Inbox actions go to the
inbox; case actions reach the guarded #212 workspace. Do not substitute the
standalone inbox URL profile for the combined requester/team campaign or rely
on its legacy default case callback. The temporary adapter was discarded.

## State and isolation evidence

The seven new tests exercise the actual canonical URL composition and synthetic
database, with separate requester and staff browsers and enforced CSRF:

- Inbox navigation preserves the case editor and access-review queue. Marking
  seen preserves the case version, event log, and outstanding access request.
- Draft saves remain rejected during clarification waiting (409, zero answers).
- A seen marker does not refresh stale evidence pins: a pre-followup draft form
  remains rejected (409), without an answer or case mutation.
- Another case's reference/text is absent; requester attempts and a revoked
  staff epoch cannot read or acknowledge inbox events.
- Missing CSRF, extra role fields, and duplicate action fields are rejected.
- Seen markers preserve approval and never expose private answer/review text
  or claim delivery in the requester projection.
- Forged panel preferences, including delivery and an unknown role-like value,
  cannot authorize a requester or restore revoked staff access (403, no-store,
  no case reference, no new seen marker or case mutation).

Local result on the final base: **64/64 passed**, PostgreSQL **17.11**, Python
**3.13.16**; system check and Ruff passed. The 64 comprise seven new compatibility
tests plus 57 existing inbox, campaign, access-review and delivery contracts.
Counts represent test cases, not product functions. The earlier run on `1109af0`
also passed 50 tests; it is superseded by the final-base run.

Reproduce in an owned disposable synthetic PostgreSQL environment:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin --major 17 --settings config.settings.campaign_review -- python manage.py test apps.team_updates.compat_review_tests apps.team_updates.tests tests.casework.test_campaign tests.casework.test_campaign_access tests.casework.test_campaign_updates tests.casework.test_campaign_delivery --noinput --verbosity 1
```

The dedicated `team-updates-compat.yml` workflow checks the exact PR head,
initializes an owned synthetic schema, checks migrations, and runs these same
64 contracts on PostgreSQL 17 and 18. Consult its run for the remote result;
the local result above does not claim a remote pass.

This is a state/isolation review only. It does not add product functionality,
grant roles, count as owner acceptance, or exercise external delivery. No main
merge, integration-branch write, deployment, or production migration was made.
NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.
