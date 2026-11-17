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
