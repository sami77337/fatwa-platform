# V8 multimedia campaign — closed synthetic review

Built above PR #226 at `05a4d5d4685f9c98f0e323d16717c896286c8d35`, verified
on GitHub before branching and again before integration. #226 remains unchanged.
Integration branch: `codex/20261117-v8-integration`; final SHA and CI receipt are
recorded in the campaign Draft PR. No main merge or production deployment.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
Synthetic owned PostgreSQL only, no external send, production credentials, real
personal data or AI approval. U03 remains unresolved and grants no organizer rights.
No completion percentage or owner acceptance is inferred.

## Try it

Use Python 3.13 and pinned `requirements-dev.txt`, with local PostgreSQL 17 binaries:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings config.settings.campaign_review -- \
  python -m apps.requester_team_journey.v8_demo
```

The helper owns and destroys a fresh isolated cluster. The demo binds only to
`http://127.0.0.1:8018`, prints random 45-minute synthetic credentials and a single
case capability, and writes eight small fixtures in `.local/qa/v8/samples/`.
In one browser context unlock `/casework/status/` using that case capability.
Upload the image, PDF and WAV samples; each append creates a new Evidence version.
In another context log into `/casework/staff/login/` as `demo-mufti`, open the same
case and preview the image, PDF and audio. Request clarification and reply from
the requester context if desired.

Open the citation editor, choose the synthetic edition, search `تجريبي`, add two
positions and a human-written synthetic answer, then save the complete list.
Open the multipart answer editor; add a PDF, then retain it while adding WAV in
the next revision. Review the text, files and citations, approve the exact current
answer as the human mufti, and separately confirm its private availability.
The requester can now open the private parts page. This is **availability**, not
signed provider delivery or proof of reading. Changing the answer, citations or
evidence requires new approval and private availability confirmation.

All feature flags default false. The demo installs temporary identity providers
scoped to this one case; entering a new case does not grant a staff scope.
V7 independent publication remains a separate editorial text-copy workflow with
a separate authorized publisher; this campaign does not claim multimedia public
publishing. No delivery connector is enabled by the demo.

## Functional contracts

- Evidence attachments and answer files are separate resources and tables. An
  evidence upload appends immutable facts; an answer upload creates a new canonical
  AnswerRevision without changing facts. Both use the same bounded private parser.
- Evidence accepts UTF-8 TXT, PDF, JPEG, PNG, WebP, MP3, M4A and WAV. Originals,
  SHA-256, byte count, detected type, filename, source and timestamp are retained.
  Evidence originals bind to one exact Evidence version and are never overwritten.
- Every GET/HEAD rechecks current cookie identity/capability and case scope. URLs
  are private route identifiers, never bearer links. Query credentials are rejected.
  Responses use no-store/noindex/nosniff and restrictive media CSP. No static/media
  directory exposes the originals. Cross-case and revoked capability reads fail.
- Ordered answer parts are immutable and bounded to eight including text. The
  manifest binds exact content, ordering, answer revision and evidence. Database
  triggers reject inconsistent bindings, sizes, MIME/kind/extensions and metadata.
  Human APPROVE and private release reparse nontext originals in the bounded worker.
  File reads verify immutable hashes and metadata without spawning a parser.
- Citation and multipart editors preserve each other's files/references in the
  new AnswerRevision. They create new child identities and never inherit approval
  or private release. The plain text editor explicitly explains its text-only result.
- Private release requires explicit confirmation by the exact approving MUFTI,
  scoped identity, provider and authentication epoch. Reads revalidate that authority
  and the current answer/evidence/manifest. Approval and release also recheck
  the actor after parsing, rejecting scope/epoch revocation during processing. Revocation, edits or new facts close it.
- Existing #225 signed-text delivery is preserved. Multipart answers are held as
  `UNSUPPORTED_MEDIA_REQUIRES_HUMAN_ACTION`, never silently sent as text alone.
  All casework profiles register the durable answer schema even with UI disabled;
  an unknown profile fails closed instead of ignoring media. No availability page
  creates delivery intents or claims signed delivery/read status.
- Citation UI searches the existing edition and original heading, exact part/page,
  and selects up to twelve source positions. Signed bounded draft state preserves
  unsaved text while adding/removing/updating references. Saved original source
  metadata/version/hash is distinct from human commentary. Current catalog content
  is TOC metadata, not a claim of full-book text or verified hadith extraction.

## Processing and storage limits

Maximum 192,000 bytes per media file (TXT retains 65,536), one still image up to
4 million pixels, PDF up to 10 pages, audio up to 120 seconds with bounded channels
and sample rates. PDF active content, encrypted documents, embedded payloads and
external MP4 data references are rejected. Parsing runs in a fresh subprocess with
6-second parent timeout and POSIX CPU/address-space limits; decoded PDF content and
object counts are also bounded. Pillow/pypdf/mutagen versions are pinned.

There is **no malware scanner**, no claim that metadata parsing fully decodes every
MP3/M4A stream, and no production upload policy. Browser WAV playback and image
decoding are actually tested; PDF inline bytes/viewer are observed, but PDF
rasterization is not automatically asserted. Validation is defense in depth for
these tiny synthetic files, not a production content-safety certification.

The `PrivateStorage` protocol separates put/get from routes and validation; the
current adapter stores private inline bytes in PostgreSQL. External pointers are
rejected by the current schema. Object Storage requires a future explicit adapter,
migration and operational policy; none is configured or claimed here.

## Parallel ownership and verification

| Agent | Isolated branch/worktree | Owned files |
|---|---|---|
| attachments | `codex/20261117-v8-media`, `/workspace/v8-media` | case_attachments, private_media |
| answers_v8 | `codex/20261117-v8-answers`, `/workspace/v8-answers` | answer_media |
| citations | `codex/20261117-v8-citations`, `/workspace/v8-citations` | case_citations |
| test_runtime | `codex/20261117-v8-browser`, `/workspace/v8-browser` | V8 browser and affected V7 browser tests |
| root | integration branch, `/workspace/fatwa-platform` | shared routes/settings/approval/delivery, integration tests, demo, CI, docs |

The independent reviewer used read-only access. Changes were cherry-picked by the
single integrator; no parallel edits to shared files or main were made.

Local PostgreSQL17.12: initial integrated suite **50/50 PASS**. It includes actual
all-format uploads, immutability, rollback, authorization, composer state and old
signed-text regressions. Later focused tests cover two review findings: legacy
profile downgrade and fabricated internal media metadata/content. Results after
hardening: **18/18 PASS**, then the added authority-race negative test **1/1 PASS**.
The final integrated six contract tests plus connected browser **7/7 PASS**.
These sets overlap and are not additive; exact head and CI are recorded in the Draft PR. Old successful unaffected tests were not manually
rerun. Initial SQL CASE syntax fixture failures were corrected; no known product
failure remains. Browser harness corrections covered native PDF browser-resource
classification, layout settling and keyboard navigation after PDF screenshots.

V8 actual browser journey **1/1 PASS**: requester image/PDF/WAV upload, staff preview,
2 citations, multipart human approval, separate private availability, actual image
16x12 decode and WAV playing/duration, foreign/stale denial, RTL320/1280 and zero
external HTTP/page errors. Chromium's native PDF internal resources are counted
separately. The affected V7 connected browser test also passed with only its
citation-composer interactions updated; signed delivery/publication/withdrawal stayed.

Local Chromium154 explicitly uses `FATWA_BROWSER_SANDBOX=0` because the container's
SUID helper is unconfigured. This is not sandboxed success. CI `v8-campaign.yml`
checks the exact PR SHA, migration drift, PostgreSQL17/18 and sandboxed Chrome on
PG17, with artifacts. PG18 browser is intentionally skipped. Local PG18 and
sandboxed browser are not claimed. Evidence paths: `.local/qa/v8/` and CI artifacts.

The unread remainder of the truncated V8 citation specification is not implemented
or guessed. Source rights/full text, production storage/scanning, production
identity/delivery, U03 and acceptance gates remain unresolved. AGENTS.md, scope and
decision/testing instructions already read for V7 remain applicable; `.agents/skills`
was absent. No extra governance layer or PR per small edit was introduced.

### Initial remote CI and migration-test correction

At `7309cde99b5350c9a7c94b1594f432c12ec09ca2`, V8 passed 55/55 on both
PostgreSQL17/18 and its sandboxed Chrome157 browser. V7 and team workspace also
passed. Two older workflow suites failed after their populated delivery-guard
migration test rolled back casework and dependent media tables, then reapplied only
casework. Its cleanup now restores the complete migration graph before invoking
current services; the migration test and following signed-delivery test passed
locally (2/2) and the former is included in V8 CI. No product fail-open workaround
was added. FAST9 separately timed out during browser startup before any page was
visited. The Draft PR preserves both initial failures and final-head CI results.
