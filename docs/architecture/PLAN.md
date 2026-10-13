# S0 foundation plan — issue #1

Baseline: `08f9e25e8ada9af56561d815f74b2c7ec9ba7ead`, branch `codex/fatwa-foundation-20261013`. The checkout has no Django app, dependency manifest, ORM, migrations, endpoints, or backend tests.

Build a development-only Django 5.2 / PostgreSQL catalog: immutable source identities, bounded read services, explicit public serializers, temporary Arabic SSR/htmx templates, and scoped backend tests. No auth/admin/case/fatwa models or routes. Production settings fail closed while gates remain held.

S1 owns parsing/archive validation and the source import command. S0 supplies a typed, atomic dry-run-first ORM adapter accepting validated records and rejecting changed reruns. S2 owns the standalone UI; S5 owns database/CI.

Both supplied ZIPs match the specified SHA-256. The predecessor uses read-only SQLite and a Django adapter without ORM or migrations; its embedded secret/debug settings and original datasets are not copied. Input scripts are untrusted text and never executed.

No Python interpreter/PostgreSQL client/running Docker daemon is currently available. Runtime checks must be NOT_RUN. Archive identity verification does not prove source validation, ORM import, PostgreSQL compatibility, or acceptance of gates.
