# V9 — origin, knowledge and connected workflows

Synthetic development only. **Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED /
Production NOT_DEPLOYED / formal acceptance not established.** No main merge,
external message, public webhook, real account, production key or AI religious
decision is part of this campaign.

## Base and ownership

The verified base is draft PR [227](https://github.com/sami77337/fatwa-platform/pull/227),
`81ccdb0f0fd25521e61ed65f098a124324139967`. V8 stays intact. One coordinator owns
`codex/20261117-v9-integration` and shared routing/settings/templates. Independent
Cloud tasks supplied these exact commits, all fetched and integrated:

| Lane | Branch suffix under `codex/20261117-` | Source commit | Owned implementation |
| --- | --- | --- | --- |
| A | v9-origin | 40348f2d8b2072e6b688d31664d225a5ee264958 | source_case_intake |
| B | v9-knowledge | ab55dabe9fe618cbac97f8931498e36d07418a2a | knowledge_links |
| C | v9-research | 3599ab054d5fc745ea264217b2d37e8d14363912 | case_citations |
| E | v9-composite-delivery | 2688ef2ecaf65da88efdb08349e6beb6e0988abc | composite_delivery |
| D storage | v9-storage | e06696ec42c104f9bca54d942cdc05357839be07 | private_media |
| D bindings | v9-storage-bindings | 6409d5534fef8e186ea8310cf94f77448921b0f2 | attachment/answer pointers and audited conversion |

D used real isolated local worktrees after external task creation failed before
an ID was returned. Browser and storage review used separate worktrees as well.
Parent-provided Cloud thread IDs are recorded in coordination messages; a
verified task URL was not available through this environment's tools. No task URL
is invented. There are no per-lane PRs.

## Functions to exercise

- **Origin:** offline Telegram message, YouTube comment and first-party website
  adapters retain exact raw bytes, source/message/thread identity and receipt
  hash. Idempotent intake creates or appends to the canonical Case/Evidence;
  unknown parents and ambiguous identities enter explicit human review. The
  staff case shows actual origin, including where legacy CaseSource says WEBSITE.
  Declared files use the existing validated attachment API and private storage.
- **Research:** Arabic source search, exact edition/part/page selection, preview
  and return with the draft intact, ordered multiple citations and editor notes.
  Correcting a citation preserves its predecessor and requires a new answer
  revision/review. Suggestions select existing permitted sources for human review.
- **Knowledge:** a published experimental edition can link to its existing cited
  reference and same-case transcript question. Proposal, independent approval,
  correction and withdrawal retain history. Opening transcript material requires
  a fresh explicit identity/scope grant, separate from seeing the public relation.
- **Storage:** immutable originals can reside outside database rows in a private
  filesystem adapter. Upload, read, citation/media revision preservation and
  composite resolution retain exact hashes. Authorized conversion records an
  audit transition and can round-trip legacy inline bytes. Interrupted storage
  writes roll back owner data; restore verifies exact backup bytes. Grace-period
  orphan cleanup takes binding locks and refuses to infer absence from missing
  owner schemas. No public paths/URLs are generated.
- **Delivery preparation:** the existing planner and queue store text/file/audio
  parts, current approval/evidence/capability hashes, leases and signed receipts.
  An independent signed return approval stages the complete plan. Unsupported
  parts hold the plan. Provider acceptance is unconfirmed; failures and expired
  attempts require human review without automatically resending successful parts.
  The staff workspace exports/imports the signed plan and shows part status.
  The old website-only text adapter refuses imported non-website origins.
- **Requester/library:** the requester sees a media link only after a current
  explicit private release; revocation, new facts or new revisions close it.
  A separate allowlisted summary reports signed composite acceptance, partial failure
  and complete delivery while never claiming reading or unlocking the older signed-text
  path. It closes on authority, evidence or capability changes. The closed experimental library
  searches approved editions only, filters Arabic categories, preserves search
  context, opens reviewed knowledge relations, and creates a correction candidate
  from an approved edition without editing its original or inheriting approval.

All new feature flags default to false, authorities/verifiers to None. U03 roles
remain unresolved and denied. No organizer authority is inferred.

## Test contract and evidence

The workflow `.github/workflows/v9-campaign.yml` checks the explicit PR head,
fresh synthetic PostgreSQL 17 and 18, system checks and migration drift. It runs
the affected service/HTTP/security tests, then the connected Chrome journey on
PG17 with browser sandbox enabled. PG18 browser is intentionally not run.

Local connected browser evidence on the shared implementation: PostgreSQL17.12,
Chromium154, one passing journey, explicit local `sandbox=False`, 320/1280px RTL,
zero external requests/page errors, revoked transcript access 404. Assertions:
one Case, one source binding and transcript, Evidence version3, two AnswerRevision
rows, two citations and two final answer parts, one private release, two existing
queue intents, one independently published edition and two approved knowledge
links. Publication, private availability and delivery bind the same approved
answer. Two actual filesystem objects hold the question attachment and answer
audio. CI artifacts retain result JSON and 18 screenshots, including requester delivery distinct from text access.

Additional coordinator tests cover source attachment replay on external storage,
canonical MIME aliases, incorrect requester, missing owner/source schemas,
pre-acquired locks through nested intake transactions, actual channel selection,
signed handoff/no send, revocation/new facts, published-only facets, return context
and correction approval. Component runs before integration: A23, B16+1 browser,
C27+1 browser, E17, D filesystem14 and owner-bindings38 unique affected tests.
Runs overlap; counts must not be summed into progress or acceptance.

Historical failures retained: first integration fixture assumed one capability
lookup although the service deliberately rechecks it; another omitted the
provider verifier. A MIME replay fixture supplied a duplicate keyword. Browser
harness initially tried to resolve a lease after ACCEPTED had ended it; it now
caches the exact resolved part for subsequent signed receipt events. These were
corrected and rerun. Review also found and fixed actual missing-schema GC,
legacy source-channel downgrade and MIME-alias replay defects. Final aggregate
and remote CI receipts are recorded in the campaign PR, not inferred from these
earlier component passes.

The first combined local run at `5dd2c6e` passed system/migration checks and
156/162 tests; six later source-integration tests errored because an old attachment
rollback test restored only its own app after removing dependent intake tables.
Attachment and answer rollback cleanup now restores the installed migration graph.
The affected rerun passed **9/9** (three migration checks followed by all six
integration checks). Unaffected passing local tests were not repeated. The
post-fix full matrix runs automatically on the final PR head in CI.

## Limits and V1 assessment

WhatsApp/Facebook/Instagram adapters are held pending verified payload/signature
contracts. There are no real connectors or trusted external recovery/identity
providers. Files remain bounded to V8 policy (192000 bytes maximum, text65536,
PDF10 pages, image4M pixels, audio120s); no size increase or malware-scanner claim.
Filesystem is an isolated Linux development adapter, not cloud/object storage or
a production backup service. Source622 is one book's table of contents, not full
text, a general taxonomy or fabricated quotations. Knowledge links only use
existing authorized records. Experimental publication remains closed, text-only,
independently reviewed and reversible; media is never made public.

Engineering estimate starts at the owner's **62% ±7**. The provisional post-V9 estimate is **about 69% ±8 percentage points**, a
**+7 point** change from 62%, with low-to-moderate confidence in the overall
percentage (higher confidence in the individually demonstrated functions). This
credits demonstrated connected capabilities in origin, storage, research,
knowledge and multipart delivery, while retaining uncertainty for source rights,
unresolved permissions, real identity/connectors, operational recovery/capacity,
broader Arabic search evaluation and owner acceptance. It is not an official
acceptance percentage and must not derive from line or test counts.
