# Human-operated local composite drill

Base `0f90bb4f6c4ba426055fc77a3a783c2061d6ee19`, branch
`codex/20261117-v11-pilot`. This slice owns only `apps/pilot_workbench/**`.
No models, migrations, alternative queue, production transport or shared settings
changes. **Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**

## What the operator can do

1. Review and approve the canonical multipart answer through the existing Mufti
   UI. The pilot never creates, edits or approves that scholarly answer.
2. Open the local drill for the same case. Inspect all parts, source, current
   answer/facts revisions and the exact delivery plan fingerprint.
3. Explicitly confirm a separate **synthetic return permission**. A server-injected
   ephemeral test authority signs only that currently approved canonical plan.
   The existing signed approval adapter stages every part atomically; nothing sends.
4. Choose ACCEPTED, DELIVERED or FAILED for the next eligible part and confirm.
   The existing native worker reserves that part once, resolves exact bytes, and
   the independent `OfflineProviderSimulator` signs its local fixture report.
   ACCEPTED is unconfirmed. A later human DELIVERED/FAILED action uses the same
   worker attempt; no replacement lease or automatic retry is created.
5. Inspect per-part states and verified **simulation** reports. A failure remains
   a failure requiring human review. A report never creates reading/listening
   proof or evidence of delivery over a real channel.

No Python, JSON, signing key, signature or lease token is entered in these forms.
No action loops over all parts to report success. The operator chooses each report.
The interface permanently labels this as synthetic local simulation.

## Explicit integration

Register `apps.pilot_workbench` only in the synthetic campaign profile for template
lookup. Defaults must remain:

```python
FATWA_PILOT_WORKBENCH_ENABLED = False
FATWA_PILOT_WORKBENCH = None
```

Shared `/casework/staff/` POST dispatch should route `views.ACTIONS` to `views.desk`:
`pilot_open`, `pilot_authorize`, `pilot_report`. Navigation posts `pilot_open` plus
the current authorized `case_ref`; no new URL/guard exemption is required.
`urls.py` and `settings.py` are owned test overlays, not shared production setup.
The existing loopback guard, CSRF, strict field counts and identity middleware stay.
The root may add these actions to its current-case context/navigation allowlist.

`pilot_authorize` requires `case_ref`, `revision`, `evidence_version`, `plan_sha256`,
`confirm=yes`. `pilot_report` adds `part_id`, `expected_state`, `outcome`.
All requests require existing staff authentication and CSRF; unknown/duplicate
fields and file uploads are denied. Request fields never supply authority.

After Django setup, the original canonical case and trusted directory exist, and
only in an owned isolated synthetic PostgreSQL profile, inject one fixture at
startup. Both the existing composite and answer-media features remain separately
configured. Example shape (replace symbols with the actual seeded identity/case):

```python
from django.conf import settings
from apps.pilot_workbench.fixtures import (
    FixtureOperatorAuthority,
    setup_synthetic_fixture,
)


class Operator(FixtureOperatorAuthority):
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (provider_id, subject_id, auth_epoch, case_ref) == (
            seed_provider_id,
            seed_subject_id,
            seed_epoch,
            seed_case_ref,
        ) and action in {"OPEN", "AUTHORIZE_RETURN", "REPORT_PROVIDER"}


fixture = setup_synthetic_fixture(
    operator_authority=Operator(),
    identity_provider=settings.FATWA_CASEWORK_IDENTITY_PROVIDER,
    synthetic_fixtures_only=True,
)
for name, value in fixture.settings().items():
    setattr(settings, name, value)
```

MUFTI role alone is insufficient: the typed operator authority must grant the exact
provider, subject, current authentication epoch, case and action. The native
composite service additionally requires the same current approving Mufti identity.
The settings mapping contains the fixture instance, pilot switch, and its exact
approval/provider public verifiers; it does not mutate configuration itself or
enable unrelated features. The live directory and verifier objects must remain
identical to the injected profile; replacement or absence closes the pilot.

Initialization checks explicit synthetic acknowledgement, `FATWA_PRODUCTION=0`,
the actual owned PostgreSQL database and composite opt-in **before generating any
key**. Flags alone create no signer. The return authority and provider simulator
hold separate fresh Ed25519 keys in memory; neither accepts user keys or keys from
SQL. No private key export or general signing endpoint exists. Even the private
return implementation rereads the current canonical plan under the transaction
and will not sign an arbitrary supplied payload.

## Freshness, transaction and memory boundaries

- All application operations use the existing guarded case/composite/queue
  services. Case, answer, evidence, origin, manifest, capability profile, current
  approving identity and the independent return permission are rechecked.
- An unsupported kind/MIME/size or missing signed receipt capability blocks the
  entire staged plan. No part is dropped, converted to text or replaced by a URL.
- Human forms pin both canonical versions, full plan hash and selected part's
  current queue state. Replayed confirmation, stale forms, foreign parts and
  non-next STAGED selections cannot create another attempt.
- Current operator grants, identity and exact injected profile are checked before
  and after action work. Return permission is reverified after provider reporting
  before commit, so revocation/expiry during a report rolls the operation back.
- Fixture lifetime is 30 minutes; each independently confirmed return permission
  lasts at most four minutes and no longer than identity/fixture lifetime.
  Expiry is not a reason to silently refresh a permission or retry an attempt.
- At most 64 issued fixture permissions and 32 active cached native attempts per
  fixture. The cache holds only native WorkerLease secrets and already resolved
  immutable bytes, bounded by the existing eight-part/192000-byte limits; queue
  state lives only in PostgreSQL. Tokens/bytes/signatures are never rendered.
- The fixture lock is acquired before the canonical transaction. Attempt memory
  is published/removed only after database commit. Public service entrypoints
  must be called standalone, not within a caller's outer `transaction.atomic`.
  Runtime/maintenance guards must enclose the call without changing this boundary;
  integration must review any future transactional maintenance wrapper explicitly.
- Restart, lost worker memory or replaced fixture keys close incomplete actions.
  No lease is reconstructed or reserved again. Use the existing composite desk
  for explicit expired-attempt reconciliation; this pilot cannot fabricate missing
  signed historical evidence. Terminal failed/delivered parts are never re-leased.
- Ephemeral keys and worker memory are not backed up or restored. The module never
  starts a background worker, network connector, sender, scheduler or recovery job.

Library/publication/private-answer release decisions are separate and unchanged.
Canonical delivery projections record this fixture under `composite-simulator`;
that is an offline test provider, not a claim about a live source channel.

## Focused verification

```sh
python infra/dev/with_casework_postgres.py \
  --pg-bin /path/to/postgresql/17/bin --major 17 \
  --settings apps.pilot_workbench.settings -- \
  python manage.py test apps.pilot_workbench.tests --noinput
```

The suite uses real PostgreSQL and native HTTP/CSRF forms: human-approved
text/file/audio → explicit independent permission → local accepted/delivered/
failed reports; no automatic case approval, no JSON, one attempt per part,
partial failure without a completion/read claim. It covers flags/bootstrap guards,
typed exact authority, profile mismatch, scope/epoch/role withdrawal, stale
versions/hash/part state, foreign/non-next parts, late revocation rollback,
permission expiry, restart/memory loss, CSRF/unknown fields and concurrent
confirmation. Historical failures and final counts belong in the handoff evidence;
no browser/full-campaign pass or production permission is inferred from HTTP tests.

Local evidence on PostgreSQL17.12 / Python3.13.5: initial 11/11 tests passed;
following canonical-signing/bootstrap/restart hardening, 16/16 passed. After adding
the final return-permission recheck, the new late-withdrawal test and two affected
native/concurrent journeys passed 3/3. This is **17 distinct passing tests**, not
30 independent tests. No test failure remained. Initial compact test formatting
triggered Ruff E701/E702; formatting corrected those before final lint checks.
Ruff check, format check and whitespace check pass. Browser, PostgreSQL18 and the
combined V11 campaign are **NOT RUN in this slice** and remain integrator-owned.
