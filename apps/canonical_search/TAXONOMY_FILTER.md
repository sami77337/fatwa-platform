# Reviewed taxonomy filter — additive development capability

This optional filter composes the **existing** canonical FTS/literal/fuzzy
retrieval with the **existing** reviewed provisional fiqh tree. It is not a
global taxonomy, an AI scientific judgment or a change to Mufti approval.

## Contract

- Unfiltered canonical search still works when the taxonomy module is off.
- A filtered search requires the development taxonomy application and its
  independently configured authority, a human-APPROVED exact tree version and
  a concept present in that version. Both the tree and version must be readable
  and the tree searchable for the current identity.
- The caller may select only that concept, or it and its actual descendants
  inside that immutable version (bounded to 64 nodes). No fuzzy mapping,
  historical category rewrite or implicit migration is performed.
- A match contributes to ranking/counts/index statuses only when its case is
  currently searchable in canonical search, searchable under taxonomy authority,
  has a current reviewed binding on **the selected version**, is in ANSWERED
  stage, and retains the matching approved answer and evidence version.
- READ on each selected binding is checked separately. Both the taxonomy
  boundary and the original search/source boundary retain their own identity,
  permission, canonical-history and deadline checks through the final HTML
  rendering. Taxonomy locks are obtained before canonical case/index locks.
- Only metadata pins and UUIDs, not copies of case text, are stored in the
  taxonomy filter. Source openings from filtered results carry a browser-bound,
  expiring signed selection and recheck the classification at the moment of
  opening. Previous/next navigation retains the same signed selection.
- Existing ordinary `cs_search` form and API remain unchanged. New strict
  `cs_taxonomy_search` form uses UUIDs from the native taxonomy desk; these
  are intentionally not inferred from book 622 or from model suggestions.
  Pagination retains version, concept, subtree choice and canonical scope.
- No extra current-source right, CITE, PUBLISH, EXPORT, MUFTI approval or
  external delivery permission can be obtained by this filter.
- Default off through `FATWA_DEVELOPMENT_TAXONOMY_ENABLED`; disabled profiles
  do not gain an input surface or a taxonomy dependency.

## Evidence boundary

The five added service/native regression cases live in
`apps.canonical_search.test_taxonomy`, registered in the existing PostgreSQL
17/18 aggregate via `infra/dev/functional_verify.py`. These synthetic checks
exercise primary/additional/subtree matching, exact version identity, unreviewed
and denied trees, late authorization loss, strict HTML form and signed opening.

Passing those tests is required but not a certification of original owner point
223/229/269, full scientific taxonomy quality, real data coverage, or Gate B.
No final visual design changes, migration, main merge or production deployment.
