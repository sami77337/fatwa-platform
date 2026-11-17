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
The service supports 1–12 explicitly selected references; the native form saves
one selected citation per new revision and clearly states that previous citations
remain in previous versions. It does not silently copy references forward.
Stale evidence/case forms, changed fingerprints, nonexistent references, duplicate
selections, extra fabricated source fields, and pending clarification fail closed.

The PostgreSQL trigger prevents changing/deleting a snapshot, mismatching source
metadata, and appending citations after the transaction that created the answer.
If any citation insert fails, the new answer, event, and cleared approval roll back.
`read_citations` is scoped and can select an exact older answer ID from the same
case. `citations_for_locked_answer` is an **internal** projection for publication
services already holding their authorized case lock; it is not an access endpoint.

Focused tests (fresh PostgreSQL 17/18 only):

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/pg/bin --major 17 \
  --settings apps.case_citations.settings -- \
  python manage.py test apps.case_citations.tests --noinput
```

The source fixture is the repository's five fabricated reference headings with
the explicit synthetic book identity `622`; no real source archive or data is
claimed. Tests cover search, literal preservation, version binding, approval
invalidation, authority, fabricated/stale inputs, rollback, database immutability,
and authenticated CSRF-protected RTL forms. Campaign browser evidence is recorded
by the integration suite. No AI writing/approval, external send, or production
access. **NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD**.
