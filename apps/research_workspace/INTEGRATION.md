# V11 research workspace — lane F handoff

Base: PR #229 / `0f90bb4f6c4ba426055fc77a3a783c2061d6ee19` (remote verified before checkout).
Branch: `codex/20261117-v11-research`. Ownership: this directory only.
V9/V10 branches preserved. No model, migration, shared config, dependency, or existing app changed.

## Connected functions

- Arabic reference search uses `case_citations.search_sources` / the existing `reference` catalog, with exact edition, printed part/page filters. Search preserves original headings; normalization does not replace source text. The strict `research_bridge.bridge_reference` rechecks resolver evidence and all catalog pins on opening/citing.
- Case-linked lessons/transcripts use the existing immutable `transcript_case_links` bundle, linkage/evidence checks and independent `KnowledgeAuthority.OPEN_TRANSCRIPT` permission. Search covers original question/source answer/source ID; opening retains exact text and time offsets. Source answers are explicitly not approved case answers.
- Only currently approved, available `knowledge_links` relationships for the case's experimental publications appear. Proposals, withdrawn links, invalidated editions and foreign cases stay outside results. Both relation and underlying reference/transcript rights apply on opening.
- Case attachments and current-evidence answer media download through existing private readers and SHA verification. Audio remains audio. Media are not asserted to be related to a lesson without an existing verified relationship.
- An explicit human-confirmed reference selection appends to the latest **saved, current-evidence** answer via `save_cited_answer`. Existing citations, original answer text and media are retained. Canonical history records a new revision; prior approval/private availability cannot carry over. Rights revoked during saving roll the transaction back. An old answer after new evidence must first be edited/saved in the existing answer editor.
- Native CSRF-protected forms use signed, 30-minute, browser/provider/subject/auth-epoch/case-bound return state with exact revision/evidence versions. Opening and back navigation restore filters; stale state fails closed. Tokens contain identifiers/pins/filter state, not copied transcript text or stored asset URLs.

## Coordinator wiring (shared ownership, deliberately not edited here)

1. Add `apps.research_workspace` to installed apps for template discovery.
2. Keep `FATWA_RESEARCH_WORKSPACE_ENABLED=False` by default; opt in only to the owned synthetic profile (`FATWA_PRODUCTION=0` and existing owned DB guard required).
3. Route POST actions in `views.ACTIONS` at the existing `/casework/staff/` dispatcher to `views.workspace`. Retain normal case-workbench dispatch for other actions/GETs. The owned `urls.py` / `settings.py` compose a standalone scoped entry list solely for local testing; do not replace the integrated desk with that landing page.
4. Insert `{% include "research_workspace/entry.html" with research_case_ref=selected.public_ref %}` (adapt the current canonical case variable only). All actions carry `case_ref` and current identity remains authoritative.
5. Add `path("research-workspace.css", views.styles)` (public non-sensitive CSS, private/no-store response). The desk loads this same-origin stylesheet; it adds bounded keyboard-visible selects without editing shared CSS or weakening CSP.
6. Existing feature prerequisites: `FATWA_CASE_CITATIONS_ENABLED`, `FATWA_KNOWLEDGE_LINKS_ENABLED`, `FATWA_EXPERIMENTAL_PUBLICATION_ENABLED`, `FATWA_ANSWER_MEDIA_ENABLED`, `FATWA_CASE_ATTACHMENTS_ENABLED` as applicable. Existing case access, publication gates and independent transcript permission remain mandatory.

Service calls: `search(**case_actor, query, kind, edition_id, printed_part, printed_page)`, `open_resource(**case_actor, resource)`, `add_citation(**case_actor, resource, note, expected_revision, expected_evidence_version)`.
`case_actor` contains `case_id`, `subject_id`, trusted `provider`, `synthetic_fixtures_only=True`.
Kinds: `all`, `REFERENCE`, `TRANSCRIPT`, `KNOWLEDGE`, `MEDIA`. Results are bounded to 40; catalog search retains its existing 20-hit bound. Narrow filters to inspect further material; no exhaustive corpus-search claim.

## Contract for source_rights

The C contract at `dd610e27d3bd08871259388801844519669f04f1` was read and exercised against real PostgreSQL without merging/copying its files into this branch. `source_rights_adapter.SourceRightsAdapter` is the ready integration adapter:

```python
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter

FATWA_RESEARCH_WORKSPACE_RIGHTS = SourceRightsAdapter()
```

Install C and configure its synthetic feature flag/independent `SourceRightsAuthority` as documented by C; its locked predicates remain fail-closed when absent or unapproved. This adapter maps reference discovery/open to **READ**, citation appending to **CITE** (including every retained citation), transcript discovery/search/open to **READ** plus existing private authority, and current knowledge navigation to **READ + RELATE** on the exact underlying source. It calls only C's locked read predicates, after our existing canonical case lock; it never acquires C's namespace311 advisory lock or invokes C mutations inside that transaction. The edition selector requires at least one registered readable exact position in that edition; all result positions are individually checked, so this is not an edition-wide grant.

C does not cover attachments/answer media: the adapter denies those by default. An approved, server-owned `ResearchRights` implementation can be passed as `SourceRightsAdapter(media_rights=...)` for exact case/media/hash/action grants. Do not use `tests.SyntheticRights` as an actual policy. No source READ grant implies media access, anonymous preview, publishing, or private transcript CITE.


Set `FATWA_RESEARCH_WORKSPACE_RIGHTS` to an instance/subclass of `rights.ResearchRights`.
Absent/wrong type => deny. Exceptions => unavailable/closed. Only literal `True` grants.

```python
permits(*, provider_id, subject_id, auth_epoch, case_ref, action, resource) -> bool
```

`resource` is the immutable `rights.Resource`, never client-created policy input. Server resolves and verifies it again when used.

| Kind | Identifier | SHA and additional pins |
| --- | --- | --- |
| EDITION | canonical edition PK | ingest_checksum + edition_id/source_namespace/source_book_id/edition_key/archive SHA/input SHA |
| REFERENCE | `edition_id:source_row_id` | canonical citation source_sha256 + all edition/source pins above |
| TRANSCRIPT | canonical case TranscriptLink UUID | SHA256 of queue-canonical JSON `[upload.sha256, question_sha256]`; upload SHA includes source answer/provenance |
| KNOWLEDGE | canonical KnowledgeRevision UUID | snapshot_sha256; underlying source rights additionally required |
| ATTACHMENT | canonical CaseAttachment UUID | original bytes SHA256 |
| ANSWER_MEDIA | canonical AnswerPart UUID | original bytes SHA256; restricted to latest current-evidence answer |

Actions are separate grants: `DISCOVER` (listing metadata), `READ_METADATA` (full metadata), `SEARCH_TEXT` (matching actual transcript text), `READ_TEXT` (view actual transcript text), `CITE` (append verified reference), `READ_MEDIA` (download exact original bytes). Empty transcript searches need DISCOVER + READ_METADATA; nonempty searches need DISCOVER + SEARCH_TEXT. Every transcript inspection also requires the existing independent `KnowledgeAuthority` grant. A relation grant cannot bypass its underlying reference READ_METADATA or transcript READ_TEXT. Reference titles through knowledge search require both relation and reference DISCOVER.

Bind grants to exact current identity/case/resource/hash/action and the approved rights record, not a display title or role-wide wildcard. Repeated checks are intentional to catch revocation during parsing, opening and canonical writes. `tests.SyntheticRights` is fixture-only, not a shipping rights policy. No production rights signer, credentials or automatic grants are supplied.

## Evidence and limits

Focused final evidence (fresh owned PostgreSQL **17.12**, Python 3.13.16):

- 11 service tests PASS plus 3 HTTP tests PASS (14 distinct tests). Final service-bearing run: `/tmp/v11-research-tests-final.log` (13 tests at that point); added return-search revocation case + affected HTTP recheck: `/tmp/v11-research-http-browser-final.log`.
- 1 Playwright 1.58 / Chromium 154.0.8037.57 live HTTP journey PASS: transcript exact text, return filters, exact audio bytes download, two identical catalog headings distinguished by canonical identity, explicit human citation insertion, saved revision. Keyboard Enter navigation, RTL/no horizontal overflow at 320/1280, zero external requests, zero page errors/HTTP failures. Screenshots `.local/qa/v11-research/` (local evidence, not committed).
- Three additional cross-lane PostgreSQL adapter tests PASS with the actual C code at the pinned SHA: exact READ/CITE distinction, expired/restricted/revoked rights, distinct imported edition isolation, transcript READ and relation READ+RELATE, media default deny. Two passed in `/tmp/v11-research-ledger.log`; the lifetime test initially also expired the synthetic actor (correctly denied case access). A second fixture attempt left that actor beyond its allowed one-hour validity horizon after restoring time (`/tmp/v11-research-ledger-final.log`); access again correctly closed. The final fixture restores the clock and short-lived identity together and passes in `/tmp/v11-research-ledger-final2.log`. No C files were changed or committed. Total distinct service/HTTP/cross-lane tests: **17**, plus **1** browser journey.
- Temporary C composition: `git archive <C SHA> apps/source_rights` extracted into `/tmp/v11-rights-integration`; `/tmp/v11-rights-integration/combined_settings.py` appends that directory to `apps.__path__`, imports the owned research settings and adds `apps.source_rights`. With `PYTHONPATH=/tmp/v11-rights-integration`, run the PostgreSQL wrapper using `--settings combined_settings -- ... manage.py test apps.research_workspace.test_source_rights`. Its three tests explicitly skip in an isolated checkout with C absent; no skipped result is counted as a pass.
- Local Chromium used `FATWA_BROWSER_SANDBOX=0`; sandboxed-browser/PG18 validation belongs to the campaign integrator, not claimed here.
- `ruff check`, `ruff format --check`, Django check, `makemigrations --check --dry-run`: PASS; no model changes. No unaffected prior suite rerun.
- Historical attempts retained: initial HTTP test expected 302 instead of actual 303 (two fixture assertions, corrected); first browser attempt used an ambiguous identical-title locator, second targeted fixture row3 which was outside the `فرع` query; final selects the correct canonical row5 and passes. Logs `/tmp/v11-research-tests.log`, `/tmp/v11-research-browser.log`, `/tmp/v11-research-browser2.log` preserve those failures.
- Synthetic five-row catalog fixture only (`tests.reference.test_catalog.fixture`, book ID changed to622 by existing citation fixture, archive `a`*64/input `b`*64); these are explicit fixture pins, **not** owner archive verification. No original book text, source acceptance or scientific correctness claim.
- No global transcript corpus import/search, guessed lesson playback URLs, generated quotations, invented relationships, AI answers, external requests, production policies or public publication. Transcript-to-case linking stays with its existing intake/evidence service; this workspace does not invent a new citation model for transcripts.
- The tested C rights adapter is delivered; configuring C's authority and any exact media policy, installing C, and integrated desk wiring remain coordinator tasks. Existing reference/citation/knowledge endpoints retain their existing policies; this directory does not claim to retrofit all other surfaces with the new rights seam.

Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**; **NOT_DEPLOYED**.
No new progress estimate; owner's reference remains 74% ±8, not acceptance.
