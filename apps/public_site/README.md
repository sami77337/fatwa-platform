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
