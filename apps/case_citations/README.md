# Synthetic case answer citations

`FATWA_CASE_CITATIONS_ENABLED` defaults to false in the campaign profile. Enable
it only in the explicitly owned synthetic review/test environment. Add the app,
apply its migrations, and dispatch `views.ACTIONS` to `views.desk` at the existing
guarded `/casework/staff/` endpoint. The current scoped MUFTI session is required
for search, selection, saving, and reopening a source. Entry form fields are
`action=citations`, `case_ref`, and CSRF token; no source identifiers in URLs.

Search selects an existing book-622 edition, then a documented heading/printed
location. Resolution reuses `reference` normalized search and `reference_links`
`DjangoCatalog`, `resolve`, and `SourceIdentity` exact provenance validation.
The available catalog is **TOC metadata**, not full book text. The original heading
and full original hierarchy are snapshotted separately from the human editorial
note. The UI never labels a note as an original quotation or claims scholarly
authentication. Full-text quotations and hadith authentication require verified
source material and remain unavailable.

`save_cited_answer` takes ordinary case service arguments plus exact
`expected_revision`, `expected_evidence_version`, `text`, and `selections`:

```python
[
    {
        "edition_id": 1,
        "source_row_id": 2,
        "source_sha256": "<fingerprint returned by read_source>",
        "editorial_note": "<human note; never original source text>",
    }
]
```

Each save creates a **new canonical AnswerRevision** and clears prior approval,
within the existing locked case history transaction. It writes no parallel case
or answer records. Each immutable citation belongs to that exact answer revision.
The service and native editor support 1–12 explicitly selected references.
Opening the editor shows the latest answer and its complete source list. Search
by explicit edition, exact printed part/page, and/or normalized title terms;
select a specific source row, add several positions, remove a selection, or
update its human note. The original source is always displayed separately.
Search/add/remove/update actions preserve the unsaved answer text. None creates
an answer revision. Final confirmation explicitly reviews and saves the whole
displayed list with one new canonical answer; older lists remain unchanged.
Stale evidence/case forms, changed fingerprints, nonexistent references, duplicate
selections, extra fabricated source fields, and pending clarification fail closed.

The native composer uses one POST form with at most **12 submitted fields**,
including CSRF and final confirmation, regardless of reference count. Its signed
30-minute scratch state binds the list and original revision/evidence pins to
the current case, provider, subject, identity epoch, and browser CSRF secret.
It is not a database record, session grant, or answer. Expired/tampered/cross-case
state is rejected. A stale final save retains the submitted text and original
pins for copying/review; it never silently rebinds them to newer evidence.
Leaving the page or ending the identity session can discard unsaved work;
the UI makes this limitation explicit. No local-storage or draft cookies.

Integration: add `citation_compose` to the shared staff action dispatch (or use
the exported `views.ACTIONS`). The isolated test settings use `case_citations.urls`
to compose this handler with existing campaign routes without changing shared
configuration. Existing V7 single-reference actions remain compatible.
The composer command is `search`, `add:<edition>:<row>`, `remove:<zero-index>`,
`note:<zero-index>`, or `save`; only `save` with `confirm=yes` writes an answer.

The PostgreSQL trigger prevents changing/deleting a snapshot, mismatching source
metadata, and appending citations after the transaction that created the answer.
If any citation insert fails, the new answer, event, and cleared approval roll back.
`read_citations` is scoped and can select an exact older answer ID from the same
case. `citations_for_locked_answer` is an **internal** projection for publication
services already holding their authorized case lock; it is not an access endpoint.

Cross-editor preservation uses `clone_citations_for_new_answer(previous, answer)`
inside the caller's authorized case transaction, after the new canonical answer
and its SAVE_ANSWER event exist. It revalidates the source snapshots and creates
new citation IDs for the next revision of the same case. The citation editor
likewise calls `answer_media.services.clone_parts_for_new_answer` when that
optional app is installed, preserving the previous answer's associated files.
Neither helper inherits approval or private release; failure rolls back the
entire answer edit. No nested case lock or parallel answer is created.

Focused tests (fresh PostgreSQL 17/18 only):

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/pg/bin --major 17 \
  --settings apps.case_citations.settings -- \
  python manage.py test apps.case_citations.tests apps.case_citations.composer_tests --noinput
```

The source fixture is the repository's five fabricated reference headings with
the explicit synthetic book identity `622`; no real source archive or data is
claimed. Tests cover search, literal preservation, version binding, approval
invalidation, authority, fabricated/stale inputs, rollback, database immutability,
and authenticated CSRF-protected RTL forms. `apps.case_citations.browser_tests`
exercises actual multi-selection, draft preservation, save and reopening at
320/1280px with screenshots/JSON under `.local/qa/v8-citations/browser`.
No AI writing/approval, external send, or production
access. **NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD**.

## V9 research and correction workflow

V9 extends the V8 composer; it does not introduce another answer store or duplicate
multi-citation search. All changes remain in `apps/case_citations/**`.

- Open a result or selected reference inside the native POST editor, then return
  with the answer, search filters, selected order and note field intact.
- Ask for up to five **existing normalized heading matches**, shown separately as
  unapproved proposals. Preview and explicitly select one before the final human
  save. No AI, external service, generated quotation, scientific confidence score,
  hadith database, full book text or rights expansion is involved. A short/empty or
  unmatched phrase gives no proposal. A proposal is temporary signed draft state,
  not a durable scientific relationship or an approval.
- Move citations up/down with keyboard-accessible buttons. Notes and order are
  saved with the canonical answer revision; old snapshots remain unchanged.
- For a saved citation, choose **تصحيح مصدر الإحالة**, enter its correction reason
  in the existing note input, then choose **استبدال بالإحالة المصححة** on a result.
  The existing editorial note remains separate and can be changed using its note
  button. Save the complete list to record the correction. No extra POST field
  is added; the 12-field form limit remains intact.
- Read history in pages of 20 answer revisions, showing the original snapshot,
  note, answer author/time/evidence version, and old/new correction source and
  reason. Unresolvable current sources are marked historical and unavailable for
  opening, not rewritten or presented as verified current evidence.

`CitationCorrection` links the new immutable citation to one citation on the
immediately preceding answer of the **same case**, with a nonblank reason of at
most 2,000 characters. The record is created in the same transaction as the new
answer. PostgreSQL rejects mutation, late insertion, reverse/stale lineage and
cross-case links. Failure rolls back the answer, events, files and cleared
approval. The existing media-clone helper preserves originals and fingerprints;
approval and private availability are never copied.

### Final integration contract

Apply migrations `0003_citationcorrection` and `0004_correction_guards`. Keep the
existing app, feature flag and `citation_compose` dispatch already installed by
V8; **no shared route, settings or media change is required**. The signed workspace
uses salt v2; a pre-upgrade scratch form must be reopened (saved answers unaffected).
All reads/writes retain current scoped MUFTI authority and synthetic guards;
U03 researcher/organizer permissions have not been invented.

Existing `selections`, `read_citations` and clone-helper contracts are unchanged.
`save_cited_answer` additionally accepts an optional `corrections` list:

```python
corrections=[{
    "ordinal": 1,  # one-based position in the new selections list
    "previous_id": "<citation UUID from latest answer of this case>",
    "reason": "<human correction reason>",
}]
```

`read_citation_history(**scoped_case_args, before_revision=None)` returns
`{revisions: [...], next_before: int | None}`. This is a **private staff projection**
including actor identities, not a public-library payload. Existing publication
callers continue using `citations_for_locked_answer` under their independent
scope and approval contracts. `suggest_sources` takes `search_sources` arguments
and returns at most five exact-source candidates with status
`PROPOSED_REQUIRES_HUMAN_REVIEW` and method `EXISTING_NORMALIZED_HEADING_MATCH`.
Integrators must not interpret either as verified scholarly relevance.

New composer commands: `open:<edition>:<row>`, `return`, `suggest`,
`accept:<edition>:<row>`, `up:<index>`, `down:<index>`, `correct:<index>`,
`replace:<edition>:<row>`, `cancel_correction`, `history:latest`,
`history:<before-revision>`. Proposals require a matching signed candidate before
acceptance; ordinary manual source selection remains available without proposals.
Only `save` with `confirm=yes` creates an answer/correction record.

Add `apps.case_citations.research_tests` and
`apps.case_citations.research_browser_tests` to the unified V9 focused run. Browser
artifacts go to `.local/qa/v9-research/browser/`. Local evidence and limits are in
[V9_RESEARCH_REPORT.md](V9_RESEARCH_REPORT.md).
