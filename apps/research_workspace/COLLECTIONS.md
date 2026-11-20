# Private research collections, saved searches and comparison

This development feature implements a new saved workspace within an already
authorized case. It does not add a researcher role or grant case/source access.
`FATWA_RESEARCH_COLLECTIONS_ENABLED` is **false by default** and requires the
existing research workspace, owned synthetic PostgreSQL guard and
`FATWA_PRODUCTION=0`. It is not a production policy acceptance.

## Working user journey

1. Open the case's research desk and **مجموعاتي البحثية الخاصة**. Create a named
   collection. Collections belong to the exact provider, subject and case.
2. Search existing permitted materials, open their exact provenance, then choose
   **حفظ في مجموعة خاصة**. The selection retains canonical resource identity and
   source/version pins, not search ordinal, rendered source text or file bytes.
3. Add/edit a private note, move an item up/down, remove an item, rename a
   collection, or archive/restore the collection. These actions do not change
   canonical facts, answer revisions, scholarly approval or published content.
4. Open one saved item or select two/three for comparison. Each panel preserves
   its exact original metadata/text/time range and source/version identity.
   Reference headings remain explicitly identified as index entries, not book
   text. Unrecorded authorship is not invented. Notes remain separate from source
   material. Mobile comparison stacks readable cards rather than forcing narrow
   columns. Each panel links to the existing exact source view; a reference can
   then use the existing human-confirmed answer citation action.
5. Save the current query/filter state with a name. **إعادة البحث الآن** explicitly
   executes the search with current rights and current source records. New
   results do not enter the selected collection automatically. No background
   search, subscription, result cache or notification is created.

Current saved resource kinds are `REFERENCE`, `TRANSCRIPT`, and `KNOWLEDGE`.
They use the existing verified catalog, linked transcript and human-approved
knowledge services. This does not add a hadith corpus, general fatwa corpus,
arbitrary URL bookmark, full book text, or original media download grant.

## Requirement trace and remaining scope

| Owner point / specification | Delivered boundary | Remaining qualification |
|---|---|---|
| 338 / U12-012 | Named private collection bound to current provider/subject/case | Cross-case/global researcher workspace and sharing policy are not enabled |
| 339 / U12-013, U12-016 | Exact existing book-index, linked transcript and approved knowledge resources; separate editable private notes | The broader original list of fatwas, hadith, lessons and books is not all supplied as a corpus here |
| 340 / U12-015 | Named saved query/filters; explicit fresh rerun without changing selected items | No automatic subscription or background search |
| 341 / U12-017 | Two/three currently authorized exact materials together, with provenance and available original context | No generated comparison, synthetic scholarly conclusion or transfer of a ruling to a new case |

These mappings are development evidence, not a claim of four complete product
requirements or an increase of 10–12%. Historic V12–V14 classifications remain
unchanged. The full integrated campaign supplies its own current SHA/browser and
recovery evidence.

## Integrity and privacy

- Every public service is admitted through `@mutation_service`. The canonical
  case lock surrounds collection operations. Mutations require current case and
  evidence versions plus the collection's own revision. An independent note edit
  never increments canonical case/evidence versions.
- Owner filtering occurs before fetching a collection. No possession of a UUID
  or signed form grants ownership. Browser form state is signed, short lived and
  bound to provider, subject, auth epoch, case and browser proof. Native forms
  retain CSRF and exact-field validation.
- Source rights and immutable identity are resolved on adding, opening and
  comparing. Reading an item list also verifies source access before showing its
  title, pins or note. A revoked/unavailable item becomes a generic removable
  slot; its private note is hidden because it may contain a quotation.
- Collection-wide policy-epoch and rights-expiry guards surround construction
  and HTTP rendering. Final source checks prevent a later resource callback from
  leaving an earlier source authorized under withdrawn rights. Custom research
  policies must implement the existing atomic `projection_epoch` contract; the
  exact stock ledger adapter uses its locked current ledger. A policy outage
  fails closed rather than becoming an empty successful comparison.
- New rows do not confer `CITE`, independent transcript access, publication or
  requester access. Saved-search instructions may persist as the owner's own
  query, but results must be authorized again when the owner reruns it.
- PostgreSQL triggers keep collection owner bindings, item source identities and
  audit events immutable. Every accepted change appends a chained event with
  actor/epoch, canonical case/evidence pins and a digest of the resulting private
  state. Reads verify sequence, chain and current-state digest. Direct unaudited
  item edits cannot silently become the next service baseline.
- Bounds: 20 collections per owner/case, 30 selected resources per collection,
  20 saved searches, 256 collection events, title 160 characters, note 2,000
  characters, and one to three explicitly opened items. Query bounds remain the
  existing research bounds. Archive retains records and historical audit.

## Integration

The existing research dispatcher recognizes collection actions in
`views.COLLECTION_ACTIONS`. No new URL is needed. Shared profiles should retain
`FATWA_RESEARCH_COLLECTIONS_ENABLED=False` unless explicitly opting in to the
synthetic development composition. Native entry controls appear in the research
desk only when enabled. A shared Mufti tab may POST `research_collections` with
the existing authorized `case_ref`.

Migration `0001_initial` depends on `casework.0005_casemediastoragetransition`.
`0002_collection_integrity` adds the guards. New tables:

- `research_workspace_researchcollection`
- `research_workspace_researchitem`
- `research_workspace_savedresearchsearch`
- `research_workspace_researchcollectionevent`

No new private-media owner exists. Recovery must preserve these rows and their
guards with the full schema, while still failing closed on frozen mutations.

When the separate content-reporting capability is enabled through the shared
`reports_enabled` context, an opened transcript offers `report_prepare` with its
exact transcript link UUID. Reporting remains owned by that separate service;
this workspace does not infer report authority or alter the transcript.

## Verification

`apps.research_workspace.test_collections` contains 20 new PostgreSQL tests,
including four native HTTP journeys and two actual rights-ledger tests. They
exercise create/select/notes/reorder/remove/archive/restore, saved-search rerun,
exact two/three-kind comparisons, preserved canonical records, immutable audit,
concurrent single-winner note editing, late revocation rollback, hidden revoked
notes, owner/epoch/scope denial, malformed state, CSRF and stale pins.

The focused command also runs the 14 existing research contracts and three
existing source-rights integration contracts (37 tests total):

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin \
  --major 17 --settings apps.research_workspace.settings -- \
  python manage.py test apps.research_workspace.test_collections \
  apps.research_workspace.tests apps.research_workspace.test_source_rights --noinput
```

Repeat with PostgreSQL18 for the second supported major. This service/HTTP test
suite does not substitute for the integrator's protected-browser journey or
encrypted recovery test. Local run receipts are in
`.local/qa/research-collections/` and are not production evidence. The initial
implementation run exposed a validator-return mistake, corrected without changing
acceptance assertions; a subsequent fixture-name collision was corrected. The
first PostgreSQL18 startup required its provisioned library path, with that failed
startup preserved separately.

Gate B **NOT_PASSED**; C/D/E **HOLD**; Phase01 **BLOCKED**; **NOT_DEPLOYED**.
