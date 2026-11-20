# Integration contract

Install `django.contrib.postgres` and `apps.canonical_search`. Keep default settings:

```python
FATWA_CANONICAL_SEARCH_ENABLED = False
FATWA_CANONICAL_SEARCH_AUTHORITY = None
```

`apps.canonical_search.settings` is the app-local PostgreSQL test overlay. The
migration enables the trusted PostgreSQL `pg_trgm` extension. Runtime code still
requires the existing synthetic owned-database/maintenance admission and
`FATWA_PRODUCTION=0`; no production migration or role grant is introduced.

Delegate `apps.canonical_search.views.ACTIONS` to `workspace(request)` through the
actual campaign `/casework/staff/` dispatcher. Actions are `cs_open`, `cs_search`,
`cs_rebuild`, `cs_source`. The same-case tab posts `cs_open` and `case_ref` with the
existing CSRF token. No new anonymous/private GET endpoint or public search exists.

Core services accept `case_id`, `subject_id`, `provider`,
`synthetic_fixtures_only=True`. APIs are:

- `desk(**base)` — current generation status, without private source bytes.
- `rebuild(**base, expected_revision, expected_evidence_version,
  expected_generation, request_key)` — source-derived complete immutable generation.
- `search(**base, value, mode='FTS', kind='ALL', page=1, scope='CASE')` — only
  current-authorized rows/counts; `scope='SCOPED'` explicitly searches granted cases.
- `open_source(**base, generation_id, document_id)` — exact current source text;
  stale source, stale generation or withdrawn access fails closed.

The `SearchAuthority` and identity provider must expose pure atomic
`projection_epoch()` capabilities covering all grant inputs, including expiry.
The authority grants only VIEW/REBUILD/SEARCH/OPEN on exact current case scope.
It never replaces source rights. Every external callback finishes before the final
pure identity/provider/authority/source/index snapshots are compared. Render-time
changes deny the entire response and roll back a native single-command write.

The recording adapter migration depends on the installed `public_answer_media`
schema (through `0002_integrity`). Its runtime feature and authority remain
default-off independently. A usable versioned recording authority and
`TimedMediaRights` are necessary for recording text; they are not necessary for
ordinary question/answer search. The adapter uses `search_projection`, retains
its pre-callback snapshot, and calls all `assert_snapshot` byte checks followed
by all pure `assert_projection_state` checks before finishing search's own pins.
Unusable optional recording configuration excludes recordings. Configuration or
grant changes during rendering reject the response.

`RECORDING_TRANSCRIPT` hits have `segment_url` pointing to the existing guarded
`/casework/staff/recording-transcripts/<transcript_id>/segments/<index>/` route.
Their `pin` contains exact transcript/part hashes, transcript version, segment
hash/index and start/end milliseconds. The recording route rechecks current
source/read/reviewer rights; no URL serves as an access capability. SQL checks the
new document's text/timing against the immutable recording row and actual part.
No additional route, table, trigger or recovery owner is introduced by this adapter.

Two tables require recovery inventory: `canonical_search_searchgeneration` and
`canonical_search_searchdocument`. There are no new byte-object owners, media
registries, external calls, credentials, or private-file paths. The app-local
`recovery_support.py` exposes TABLES/FUNCTIONS/TRIGGERS/populate/verify_restored. It seeds
nonempty derived records through real services, including an independently
reviewed private-transcript READ grant, and verifies FTS/fuzzy plus actual missing
authority/inactive identity denials after restore. Source-rights enforcement stays
strict; restoring data does not mint a new grant.
