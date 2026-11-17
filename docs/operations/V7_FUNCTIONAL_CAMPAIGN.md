# V7 functional campaign — synthetic review only

Base: PR #225, `e4b118095cd96145f79a6af6980dac47a7179c05`, verified on GitHub
17 November 2026. No newer pull request existed at the initial check. Integration
branch: `codex/20261117-v7-functional-campaign`. The Draft PR records the final
remote SHA and CI receipt. This extends the accepted development from #207–#225.

**Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.**
No production migration, publication, sender, external message, real data or AI
ruling. No main merge. U03 remains unresolved; no organizer or assignment grants
were invented. No completion percentage is assigned; the inherited 53% estimate
is not an acceptance measure.

## Try the functions

Use Python 3.13 and pinned `requirements-dev.txt`; local browser testing additionally
used Playwright 1.57.0. Supply your installed PostgreSQL 17 binary directory below.
The helper creates, owns and destroys a fresh isolated database cluster:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings config.settings.campaign_review -- \
  python -m apps.requester_team_journey.v7_demo
```

The console shows one synthetic case capability and two random 45-minute credentials.
Open `/casework/status/` on `http://127.0.0.1:8017`, unlock that case and upload the
generated `.local/qa/v7/sample.txt`. In a separate browser context log into
`/casework/staff/login/` as `demo-mufti`, open the case, preview/download the file,
request clarification, reply as requester, then choose the citation editor.
Search `تجريبي`, select its synthetic book/edition/position, write a human fixture
answer, check the review confirmation, save and return to the case for approval.

Open the publication copy, enter title/category/redacted editorial text, then
record the privacy/meaning review. A separate context logged in as
`demo-publisher` must approve the edition independently before it appears in the
closed library. Open its detail page, search, create a correction edition or withdraw.
This demo grants both identities access to exactly its seeded case. Newly entered
cases receive no staff grant automatically. The signed-delivery verifier and lost
access authority remain unconfigured in this manual demo; the connected browser
test below exercises private answer availability with ephemeral synthetic signatures.

All new flags default false in the campaign profile. Identity and publication
authority default `None`. The demo explicitly installs temporary synthetic providers;
browser fields cannot grant roles, scope or publication rights. Public settings,
public URLs and production search are unchanged. The experimental library uses
existing editorial Arabic normalization and source citation resolution, while
remaining inside the authenticated loopback staff surface.

## Functional additions and boundaries

| Area | Usable addition | Remaining boundary |
|---|---|---|
| A | Search scoped question/followup/answer text, existing state filters, exact timestamped timeline and next human action | No assignment policy or organizer permission is assumed |
| B | Real multipart text upload, immutable private original, metadata/hash, exact evidence version, MUFTI/requester preview and download | UTF-8 `.txt` ≤64 KiB only; private PostgreSQL binary storage is a synthetic adapter, not D-031 object storage/scanner/media completion |
| C | Existing book/edition search, selected documented location, human confirmation, immutable citation linked to a new canonical answer revision | Available content is source TOC metadata, not full book text or authenticated hadith; one selection per native form, up to 12 via service |
| D | Separate editorial edition, redaction review, independent authorized approval, published-only closed library/search/detail, correction and withdrawal | Synthetic grant provider only; real publishing policy, identity provider, taxonomy, rights and acceptance remain unresolved |
| E | Own original question and textual followups, clarifications and currently authorized answer-version metadata | No drafts, internal notes, imported transcript evidence or previous unauthorized answers; #225 recovery proof and signed-delivery restrictions preserved |
| F | One connected PostgreSQL/browser journey, same case/evidence/answer/citation/publication associations | Synthetic signatures prove code paths only; no real delivery or production publishing |

New evidence invalidates current approval and previous private/public exposure.
Citation edits create a new answer revision and clear approval. Old source snapshots,
answer revisions, publication editions and original bytes remain immutable. A new
publication candidate is invisible to library search; withdrawal does not resurrect
an older edition. Human redaction is explicitly reviewed, not claimed as automatic
PII detection. Source headings and editorial notes remain separate.

## Verification

```sh
python manage.py test apps.case_attachments.tests apps.case_citations.tests \
  apps.experimental_publication.tests tests.casework.test_v7_workspace \
  tests.casework.test_v7_integration --settings=config.settings.campaign_review --noinput
FATWA_FASTBUILD_BROWSER=/usr/bin/chromium python manage.py test \
  tests.casework.test_v7_browser --settings=config.settings.campaign_review --noinput
```

Run these inside the isolated helper. The new `v7-campaign.yml` CI matrix checks
PostgreSQL 17 and 18 at the exact PR head, with sandboxed Chrome on PG17, migration
drift and stored test/browser artifacts. Local PostgreSQL is 17.12, Python 3.13.5,
Chromium 154.0.8037.57. Local Chromium requires explicit `FATWA_BROWSER_SANDBOX=0`
because the container SUID helper is not configured; this is not sandboxed success.
Local evidence is in `.local/qa/v7/`; it contains synthetic fixtures only.

Focused component checks passed before composition: attachments 10, citations 7,
publication 10, workspace history 5 new plus 23 existing tests. The integrated suite
contains 34 tests; final counts/results and CI are recorded in the Draft PR.
The browser test includes actual upload, exact byte download, foreign requester
rejection, RTL at 320/1280, independent publisher and zero external requests.
Two service integration tests additionally verify stale private/public exposure
after new evidence. The broader affected 48-test run initially passed 46 and failed
two old assertions that the owner's original question/completed clarification must
stay hidden. These were updated for the explicitly requested conversation history;
both affected tests then passed, preserving anonymous/foreign/token/draft rejection.
Earlier slice setup failures (duplicate app registration, invalid test fixture ID,
changed query-length contract) were corrected before passing slice runs; the query
bound remains 40 characters. These failures are not erased from the execution record.

Source review: `AGENTS.md`, existing campaign testing instructions, current Drive
decision log (D-007/016/027/029/031/062/067/068/069/071/072), and
`Fatwa_Platform_Scope_556.xlsx` were read. `.agents/skills` was absent in the supplied
repository and workspace. Relevant partial scope: U01-004/010/012/013/019/024,
U02-005/006/023/024/029/030/039, U08-010/012/013/015/019/022/023. No whole unit or
owner acceptance is inferred from these tests.
