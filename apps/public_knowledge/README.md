# Reviewed public knowledge and language revisions

This development app adds native human curation to the existing exact-grant
`library_preview` reader. It provides optional scholar profiles, explicit related
fatwas, separately released lesson descriptions, bounded topic navigation, and
immutable human-reviewed translations. Saving or approving an editorial record
never makes it visible anonymously. A separate, expiring release of the exact
revision and a current `PublicationGrant` are both required.

All fixtures are synthetic. Existing loopback-only, no-store and noindex
boundaries remain active. This is executable development functionality, not an
internet deployment, production publishing policy, religious approval, SEO
performance claim or acceptance of the final taxonomy/role matrix.

## Native workflow

The current authorized case has a `pk_open` entry. A curator selects an already
independently approved, current publication and supplies only display fields that
may be shown publicly. The forms never automatically copy a private question,
private source text, identity handle, link-review reason or operational statistic.

* **Scholar:** explicit display name and optional biography. The immutable private
  binding uses the actual `AnswerRevision` author's provider and subject. An
  answer's approving Mufti can be a different person. A released profile aggregates
  only exact-granted publications authored by that identity. Display names are
  never used for identity matching.
* **Topic:** explicit title, optional introduction and an exact approved parent
  revision. Parents and associations are currently within the authorized source
  case. Cycles and chains deeper than five topics are rejected. A parent revision
  change cannot silently rebind a released child.
* **Publication presentation or translation:** exact source edition, configured
  language, public title/question/description and reviewed profile/topic
  associations. Arabic uses the existing edition's unchanged title and body;
  Arabic body replacement is rejected. Other languages have independently entered
  text. An unavailable translation displays the original Arabic with an explicit
  explanation, never a generated replacement.
* **Related fatwas:** the native choices are approved exact-answer relationships
  from `scholarly_links`. Each selected relation ID is part of the immutable
  presentation payload and its human review/release. A private link's approval
  plus two public editions does not implicitly publish the relationship. A target
  card appears only while both exact edition grants and current endpoint READ
  permissions remain valid.
* **Related lessons:** choose a real approved case-to-lesson link and its exact
  public lesson ID, version and seal; then supply a separate public title and
  summary. Teacher associations must match the recorded teacher identity keys.
  This publishes reviewed descriptive metadata. No original file, private lesson
  title, media URL, provenance or source timestamp is made public by metadata READ
  permission. The separately pinned original remains intact.

A different human records REVIEW. APPROVE must be by someone other than the
curation author, its reviewer and the original answer's approving actor. An
explicit RELEASE requires its own current authority and confirmation. Its
5/15/30/60-minute duration is capped by the existing preview policy and one hour.
REVOKE targets one exact active lease; it cannot fall back to an older lease.
WITHDRAW is terminal for that revision. Editing creates another immutable
revision, whose review and release start again. Staff can open prior revisions and
their audit trail without making historical content public.

Commands require the canonical case revision/evidence version, expected editorial
version or action sequence, a unique request UUID and the current trusted identity.
Exact retries return the recorded result; changes to payload or requested release
duration conflict. Browser forms use native POST, CSRF and bounded allowlists.
Concurrent edits with the same expected version have one winner.

## Authorization and complete response composition

`PublicKnowledgeAuthority` must explicitly implement `permits` for the current
provider, subject, authentication epoch, case, action, kind and language. Its
`projection_epoch()` must be an atomic, side-effect-free revision of **every**
authorization input, including expiry. The default implementation denies. An
identity's Mufti role is necessary for the existing case interface but is never a
public release grant. Replacing the authority object is a configuration change,
even when two policy objects define value equality.

Anonymous reading resolves the recorded approving and releasing actors against
the current trusted directory. It does not turn the reader into staff. Source
edition grants, independently approved source state, reviewed editorial state,
lease expiry, actor epoch/scope and kind-specific permissions must all hold.
Missing or superseded profile/topic dependencies are removed together with their
associated content. No private actor identifiers reach a public URL or template.

The projection owns its transaction and media/rights-expiry boundaries until
HTML or XML serialization finishes. It pins canonical cases, publications,
rights-ledger rows, immutable editorial history, source configuration, exact
source display values and every deadline. Callback ordering is deliberate:
permission checks, exact source re-resolution and identity checks precede final
no-callback policy/row/source pins. A late withdrawal or policy change discards the
entire assembled response, including counts, navigation and sitemap URLs.

For scholarly integration, `public_knowledge.scholarly` is the sole anonymous
adapter. It uses the lane's internal `approved_candidates_for_locked_case` and
`projection_fingerprint` APIs, which grant no permission. The shared graph advisory
lock precedes sorted canonical case locks. Anonymous closure includes source
publication cases, other relation endpoints and lesson owner cases. Staff choices
use only the actor's authorized cases. Exact READ_LINK and READ_LESSON checks are
performed using the recorded release actor and both current endpoint scopes.
The outer boundary covers all scholarly rows and decision phantoms, live original
media bytes, authority object/epoch and identity through final rendering. There is
no `apps.scholarly_links.public_adapter` dependency.

## Reader routes and metadata

Include `apps.public_knowledge.routes` under `/library-preview/knowledge/` with its
`public_knowledge` namespace. Anonymous routes are:

| Route suffix | Visible result |
| --- | --- |
| empty | Available publications, released scholar profiles and bounded topics |
| `scholars/<public-series-uuid>/` | Explicit name/optional biography and current authored content |
| `topics/<public-series-uuid>/` | Current child topics and same-case curated material |
| `lessons/<public-series-uuid>/` | Separately reviewed/released lesson description |
| `publications/<edition-uuid>/<language>/` | Exact source or reviewed translation, relations and lessons |
| `sitemap.xml` | Current available reader URLs only |

The source `library_preview` index and edition pages have an optional native link
into these routes. The old source navigation/search is retained.

Visible HTML uses Microdata for `BreadcrumbList`/`ListItem`, `Person`,
`CollectionPage` and `CreativeWork`, including actual language/version and
`translationOfWork` back to Arabic. It does not declare private operations or
unreviewed generated content as a public answer. Native escaped HTML avoids an
inline-script CSP exception.

The sitemap is UTF-8 XML in the standard sitemap namespace. Its absolute URLs use
only an explicitly configured HTTPS origin; the Host header is not a canonical
origin. It excludes staff routes, raw source paths, draft/revoked translations and
query strings. `lastmod` is the relevant immutable revision or publication approval
time, not the time the XML was generated. The route returns unavailable if the
origin is absent or invalid. The maximum is 512 URLs within the already bounded
preview policy. Loopback-only/noindex still applies.

Standards consulted:

* <https://schema.org/CreativeWork>
* <https://schema.org/BreadcrumbList>
* <https://www.sitemaps.org/protocol.html>

These references support the implemented metadata syntax, not a claim about
search-engine indexing, eligibility, traffic or ranking.

## Integration contract

The integrator owns shared configuration, dispatcher and global navigation. This
app changes only its own files and the two existing `library_preview` view/template
files. Register `apps.public_knowledge`; install `apps.scholarly_links` for related
fatwas/lessons. Default settings are:

```python
FATWA_PUBLIC_KNOWLEDGE_ENABLED = False
FATWA_PUBLIC_KNOWLEDGE_AUTHORITY = None
FATWA_PUBLIC_KNOWLEDGE_LANGUAGES = {"ar": "العربية"}
FATWA_PUBLIC_KNOWLEDGE_ORIGIN = ""
```

Languages must include Arabic and contain at most eight explicit labels/codes.
The flag also requires `FATWA_PRODUCTION=0` and the existing owned synthetic
PostgreSQL/casework guards. There is no default authority fixture in application
configuration. Enabling scholarly features does not grant READ or publication.

Dispatch these native actions through `editor.workspace`:
`pk_open`, `pk_revision`, `pk_save_scholar`, `pk_save_topic`,
`pk_save_presentation`, `pk_save_lesson`, `pk_act`.

The optional `apps.public_knowledge.settings` and `urls` retain a standalone
entry to these same native services. The backend/native HTTP and protected
browser tests use integrated `config.campaign_urls`; the browser enters through
the visible current-case `pk_open` menu. It never posts through an invented page
or replaces the browser sandbox.

## Schema and recovery

`0001_initial` creates three tables:

* `public_knowledge_publicseries`
* `public_knowledge_publicrevision`
* `public_knowledge_publicaction`

`0002_integrity` adds immutable INSERT-only guards, exact source/author bindings,
sequential optimistic versions and independent review/lease constraints. Function
and trigger names are `public_knowledge_series_guard`,
`public_knowledge_revision_guard` and `public_knowledge_action_guard`. Public
services are registered with `platform_recovery` mutation boundaries. No new
source-media owner or duplicated original bytes are introduced.

`recovery_support.populate()` creates a separate synthetic case, preserved source
answer/publication, reviewed/released profile and English translation. Every new
table is nonempty. JSON-safe pins contain exact IDs/hashes and the original expiry,
not credentials or authority objects. `verify_restored(pins)` reconstructs explicit
synthetic fixture policies in a fresh process, verifies both reader pages and
original seals, and proves that removing identity or authority denies access.
Expired leases are not extended for a recovery test. `TABLES`, `FUNCTIONS` and
`TRIGGERS` expose the exact inventory to the encrypted recovery integrator. The
root drill verifies the full restored row/schema inventory as well as these reads.

## Evidence and requirement accounting

Service/HTTP labels:

* `apps.public_knowledge.tests`: 20 tests, including nonempty recovery support.
* `apps.public_knowledge.test_scholarly`: 9 real multi-case composition tests.
* Affected preexisting regression label: `apps.library_preview.tests` (15 tests).

The final reviewed local set passed **44/44 on PostgreSQL 17.11** (36.574s)
and **44/44 on PostgreSQL 18.7** (37.309s), using fresh owned synthetic clusters
and Python 3.13. The 29 new tests and 15 affected legacy tests are counted
separately; test counts are not requirement counts. Logs are retained locally as
`pg17-reviewed.txt` and `pg18-reviewed.txt` in the lane QA directory. Protected
browser and encrypted restoration acceptance remain the root integrator's separate
exact-commit checks.

These tests cover independent native review/release and CSRF, true translation
version lifecycle, immutable source/history preservation, concurrency, exact-grant
separation, expired/revoked leases, current identity changes, source withdrawal,
source configuration changes, policy object replacement, native editor/selected-revision history changes, and late HTML
link/authority revocation. The attribution regression uses two different actual
authors and different answer approvers, and verifies which released profile
receives each exact-granted publication. Scholarly fixtures include an actual
multipart source in another authorized case. They never grant anonymous media.

`apps.public_knowledge.browser_tests` is a separate protected Chromium journey. It
logs in three independent actors, uses visible native forms/keyboard submission,
proves approval alone is insufficient, releases and reads a profile/English
translation, returns to the unchanged Arabic, and revokes translation availability.
It checks 320/1280 layouts, private strings, unexpected HTTP/console errors and
external requests. The PASS receipt, screenshots and traces are written only after
success under `.local/qa/functional-completion/public-browser/`. Browser execution
is pending the integrator's hosted sandboxed CI; it is not claimed from local
backend tests.

The candidate whole development owner points are **13**, each tied to working
behavior below. Counts exclude preexisting generic source/publication machinery;
older scope matrices and production acceptance statuses are unchanged.

| Owner point | Newly completed bounded behavior | Direct proof |
| --- | --- | --- |
| 275 | Explicit approved related-fatwa selection, release and exact two-endpoint reader navigation | `test_scholarly` exact-grants/native-choices/withdrawal tests |
| 276 | Real linked lesson version, separately curated reviewed released metadata and reader page | `test_scholarly` source-preservation/READ/native-choice tests |
| 279 | Optional independently reviewed/released page for the recorded answer author | Native profile HTTP journey and author attribution test |
| 280 | Explicit name, optional biography and only the author's current granted content | Multi-author aggregation/source preservation test |
| 282 | Public profile excludes staff identities and operational indicators | Public whitelist and private-leak assertions |
| 459 (existing capability; excluded from new credit) | Actual navigable breadcrumbs with topic ancestry and content paths | Reader HTML and bounded-parent tests |
| 460 | Appropriate visible Microdata for profile, collection, content and language relation | Structured navigation/language assertions |
| 461 | Current exact-granted/released sitemap, correct namespace/origin/timestamps | XML/lease/withdrawal tests |
| 463 | Configured language structure and explicit original fallback | Reader/form/language tests |
| 464 | Preserved Arabic source, rejected Arabic overwrite | Source preservation and invalid input tests |
| 465 | Immutable translation versions, explicit historical reads and no stale lease fallback | Actual English v1→v2 lifecycle test |
| 466 | Published translation requires independent human review and explicit release | Approval-alone/version lifecycle tests |
| 467 | Unreviewed or withdrawn translation cannot become publicly available | Draft/version/withdrawal tests and browser journey |

**Excluded/partial:** 281 lacks a complete general-public-materials curation type.
283–284 remain bounded same-case topic curation rather than complete cross-case
knowledge hubs. 285 additionally lacks a hadith corpus and its full requested
material coverage. None of these four points is counted as wholly completed.
No new source corpus, accepted scholarly taxonomy, AI translation quality,
production release approval, public internet access or operational service-level
claim is included.
