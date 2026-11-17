# Metadata for the public catalog entry pages

The homepage (`/`) and the public source guide (`/help`) have fixed Arabic titles
and descriptions. To exercise canonical links and text sharing metadata, set
`PUBLIC_SITE_ORIGIN` in the Django settings module to the approved HTTPS origin.
The setting accepts a bare origin with an optional port or trailing slash.
No domain is configured in this branch. For example, an isolated Django test can
use `@override_settings(PUBLIC_SITE_ORIGIN="https://catalog.example")`.

When configured, these pages emit an absolute canonical link and `og:url`,
`og:title`, `og:description`, and `og:type`. The URLs use the named Django route
and exclude request hosts, forwarding headers, and query strings. No share image
has been selected. The pages represent the reference catalog and its guide.

An absent or invalid setting omits the canonical link and Open Graph fields.
Clean entry pages retain their existing indexing behavior. Requested homepage
search/filter variants, rejected query input, and unavailable catalog responses
omit sharing metadata and request `noindex`. The guide always renders the same
public text, so its query-string aliases share the same address.

To run the database-free metadata tests:

```sh
python manage.py test tests.public_site.test_share_metadata --settings=config.settings.test
```

## Homepage search pagination (2026-11-17)

The homepage previously stopped at the first 30 matches. It now renders bounded
30-result pages with previous/next/first links and continuous numbering. Links
preserve the exact query, search mode, depth and child filter. Submitting the
search form starts at offset zero. An empty later page offers recovery without
claiming the entire query has no matches. The existing 20,000 offset ceiling is
preserved and explained when it limits browsing.

Only the existing reference-catalog read services are used. This does **not**
create a fatwa publication route, infer scholarly approval, or expose drafts,
requester identities or private cases. A future fatwa catalog still requires its
own explicit publication policy. No shared routes, database models, migrations,
production settings, approval decisions or final design were changed.

Unknown/duplicate parameters and invalid offsets fail before database access.
Search and invalid responses omit canonical/Open Graph metadata and send
`X-Robots-Tag: noindex, nosnippet`, alongside existing `no-store` and
`no-referrer`. GET search terms still appear in browser history/address bars and
can be present in server access logs; the guide explains this boundary. No
analytics, cookies, third-party requests or client scripts were added.

### Scoped verification

Base: PR #209, `e000cdc22c1a0dfd1e0e38eb8fd7cfbfc392487e`.
Fixture: **public-search-pagination-v1**, 62 synthetic headings (one root,
61 matching children). This is not the owner's source archive or acceptance.

- Python 3.13.5 / Django 5.2.18 / PostgreSQL 17.12: **57/57 PASS** (45 existing
  public-page tests, 8 paging/privacy cases, 4 database journeys).
- Database journey visits all three result pages, follows a source-pinned detail,
  returns to previous results, checks exact/literal/normalized searches and
  empty-page recovery. Captured requests are SELECT-only, bounded to at most
  12 queries, and all reference rows remain unchanged. Private app tables are
  not queried and private/fatwa routes remain unavailable.
- Chromium 154.0.8037.57: **PASS** at 320×780 and 1280×900 with JavaScript disabled;
  keyboard navigation, filters, details, previous/next, reset and empty results.
  Zero page errors, external requests, cookies or horizontal overflow.
- Ruff and `git diff --check`: PASS. No PostgreSQL 18 or CI result claimed here.

Reproduce the scoped Django run against an isolated PostgreSQL 17/18 instance:

```sh
python manage.py test tests.public_site.test_pages tests.public_site.test_landing tests.public_site.test_share_metadata tests.public_site.test_search_pagination tests.public_site.test_search_journey_db --settings=config.settings.test --noinput
```

For the optional browser journey, migrate a **disposable** reference database,
seed `tests.public_site.search_fixture.seed_catalog()`, and serve the test settings
on `127.0.0.1:8039`. In a Python environment containing Playwright, run:

```sh
python tests/public_site/browser_search.py /tmp/fatwa-public-evidence
```

It uses `/usr/bin/chromium` and writes two synthetic screenshots plus a JSON
report. Local evidence was generated at that path; it is not a deployed site.
**NOT_DEPLOYED / GATES_HOLD.** No merge to main and no owner acceptance inferred.

## Source-section browsing (follow-up to #210)

Base: `57d72abe355a2a6b7675279d4d68cd2b1d596ab1` (#210).
The homepage now offers **تصفح عناوين الباب** on each source root and a labeled
source-section selector. `/?root=<source-row-id>` lists that root and all its
source descendants with the existing 30-result pagination. Search text becomes
optional only when a valid source root is selected. Depth and child filters may
then narrow the section; a keyword searches only inside it. Clearing the section
preserves an existing keyword/filter search and resets its offset, or returns to
the clean homepage when browsing without text.

The root must belong to the sole resolved reference edition and have depth one
and no parent. Unknown/nonroot IDs receive a generic 400 without source details;
invalid or duplicate numeric parameters are rejected before storage reads. Multiple
editions still fail closed at the homepage. Roots beyond the bounded first root
page remain selected when opened by a valid ID. Original source titles are escaped
without rewriting them. No approved-fatwa taxonomy or publishing policy is assumed.

Only `apps/public_site`, `templates/public_site`, and their tests change. Shared
URLs, reference services, schema, private casework and editorial routes remain
untouched. New sibling search-reference-cards work was checked: it changes only
editorial-search areas, outside this patch. The integration branch had advanced
to #210's head during this work; this follow-up stays based directly on that head.

### Follow-up verification

Fixture **public-source-sections-v1** contains 67 synthetic headings: two roots,
61 matching children in the first root, descendants through depth five, and a
matching peer in the other root. No real questions, rulings or owner corpus.

- **67/67 PASS** on Python 3.13.5, Django 5.2.18, PostgreSQL 17.12: 57 public
  regression cases plus 6 new boundary cases and 4 new database journeys.
- Real database reads cover all three section pages, isolation from the other
  root, keyword scope removal, depth-five filtering and source-pinned details.
  Captured requests use SELECT only, at most 12 queries, no private tables, and
  preserve the heading rows. Invalid roots and write attempts remain rejected.
- Chromium 154.0.8037.57: **PASS** at 320×780 and 1280×900 with JavaScript off;
  keyboard entry, section paging, detail navigation, keyword search, scope clearing,
  root switching and blank-query browsing. No overflow, external requests,
  page errors or cookies. Mobile screenshot inspected.
- Ruff and `git diff --check`: PASS. CI/PostgreSQL 18 are not claimed.

Run the prior scoped Django command with
`tests.public_site.test_source_sections` added. For the optional browser check,
seed **only a disposable empty reference database** using
`tests.public_site.section_fixture.seed_sections()`, serve test settings on
`127.0.0.1:8040`, then run:

```sh
python tests/public_site/browser_sections.py /tmp/fatwa-section-evidence
```

The local evidence directory contains two screenshots and `browser-report.json`.
Privacy boundaries from #210 continue to apply, including GET search history/logs.
**NOT_DEPLOYED / GATES_HOLD**; no main merge, publication or owner acceptance.
