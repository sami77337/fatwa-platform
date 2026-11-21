# Exact FT lookup and explicit published reference

Owner points217 and266 require direct lookup by FT and showing the reference on
the published fatwa. This development implementation uses the actual canonical
`Case.public_ref`; it does not assign a second number or expose private cases.

## Native behavior

- The staff workspace and search desk provide a native exact-reference form.
  Its existing authenticated `open` action resolves only a currently scoped
  case. Unknown and unscoped references retain the existing denied response.
- The public catalogue provides an exact FT form at `by-reference/`. Only a
  current, explicitly listed `FatwaReferenceGrant` can resolve. Private and
  unknown references return the same unavailable response without a private
  case-table search or approximate fallback.
- The exact released detail page displays its FT only when the independent
  reference grant authorizes that same publication UUID and content digest.
  A public-content read grant alone does not authorize reference disclosure.
- Corrected editions require a new exact grant. Withdrawal, changed canonical
  facts, source-right revocation, publisher revocation and expired policy close
  both reference lookup and the previously permitted numbered detail page.

## Current authority

`FATWA_REFERENCE_LOOKUP_ENABLED` defaults to false, and
`FATWA_PUBLIC_FATWA_REFERENCES` defaults to None. The production environment gate
also remains closed. Explicit synthetic configuration accepts at most64 unique
reference/edition mappings with a maximum one-hour deadline.

Each mapping binds the canonical FT, exact edition/hash and its recorded
independent publisher identity/epoch. Rendering runs inside the current public
publication boundary, with current source rights, recorded publisher identity,
directory object/epoch, finite deadline and exact policy-object checks before
and after rendering. Late changes roll back and fail closed. No historical
database row recreates an identity or a grant after restore.

## Verification contract

Focused execution passed28 tests on both PostgreSQL17.11 (27.683s) and
PostgreSQL18.7 (28.100s):12 reference contracts, one fresh-connection recovery
contract and15 existing public-catalogue regressions. These are service/HTTP
observations, not a protected browser or integrated encrypted-restore pass.

`test_references.py` exercises actual authenticated HTTP/CSRF forms, anonymous
exact lookup, independent disclosure, no private lookup, malformed/duplicate
input, current source withdrawal, superseding editions, expired grants,
replaced authority objects and late renderer revocation. Existing catalogue
tests must continue to prove that ordinary public responses disclose no
private case reference.

`reference_recovery.py` adds no tables. It reopens real persisted publication,
case and original audio bytes with fresh current trust, tests six actual denied
reads, then reopens successfully without changing source or original records.
The helper is part of the encrypted integrated recovery requirement.

The protected native journey is
`browser_references.FatwaReferenceBrowserTests.test_native_exact_ft_lookup_scoped_staff_open_explicit_public_number_and_withdrawal`.
It uses the real public and authenticated staff forms, checks private/unknown
indistinguishability, explicitly withdraws the publication, and verifies both
public URLs are unavailable afterward. Evidence includes320/1280 RTL
screenshots, both real context traces, page errors and unexpected requests.
This test must run in the hosted protected browser; local services and a test
definition do not constitute a browser pass.

No live public website, external search-index registration, production access
policy or owner acceptance is claimed. The existing deployment gates remain
unchanged.
