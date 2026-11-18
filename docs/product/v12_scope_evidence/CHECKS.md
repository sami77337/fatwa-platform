# P2 verification receipt — 2026-11-18

Scope: documentary package and its local Python validators only.
Product evidence remains pinned to `5aff9ba3cce35241b3ded27ed3428e0d4ecad768`.

- `python3 -m unittest discover -s docs/product/v12_scope_evidence -p 'test_*.py' -v`:
  **6/6 PASS**, 0.637 seconds. Includes source/derived integrity, duplicate source
  ID, incomplete continuation, nonexistent test anchor, repeated decision
  preservation and unreturned CI-run rejection.
- `python3 docs/product/v12_scope_evidence/validate.py`: PASS, source extraction
  hashes, exact 556/479 identity/text relation, all pinned code/test anchors,
  no acceptance upgrades, no P1 credit and deterministic output checks.
- `python3 docs/product/v12_scope_evidence/build.py --check`: PASS after formatting.
- Ruff check/format: PASS after correcting two semicolon style errors by formatting.
- No PostgreSQL/browser/product tests rerun: product code did not change. The
  saved remote results are observations, not new local test executions.

Retained preparation failures:

1. Original XLSX byte materialization failed with `download failed`. Full text
   retrieval then succeeded in two contiguous windows. No XLSX hash invented.
2. First build correctly failed its 72-decision invariant: D-061's original header
   has no date prefix. The parser now preserves that actual header instead of
   inventing a dated entry. D-023/024/044 repetitions and D-064/069 appendices are
   preserved as 77 occurrences of 72 original IDs. Build then passed.
3. Both main-protection read commands returned Forbidden; state remains UNKNOWN,
   not unprotected. No settings mutation or merge was attempted.
4. First lint found two E702 semicolons; formatting resolved both, then lint passed.
5. Staged whitespace check rejected CSV CRLF records before any commit/push;
   the renderer now writes LF records without changing source text or fields.

P1 remains outside this evidence snapshot. Historical product failures in V6–V12
receipts remain untouched. No owner acceptance, new percentage, permission grant,
production claim or independent re-review is asserted by this check result.

## Later P1 addition — separate from the historical P0 receipt above

The previously pending P1 snapshot is now reviewed at
`0055a5ab05c6dbe6d41a528666666f9db07f2fee`. See [P1_UPDATE.md](P1_UPDATE.md)
for the exact-head remote log evidence; the original P0 checks above remain history.
The updated local documentary suite passed **9/9** in 2.810s, with source/derived
validation and both-head code/test anchors passing. Three additions cover P0
preservation, wrong-head rejection and missing test pass on one major. Ruff fixed
one import order issue; final lint/format passed. No product checks were rerun.
These nine tests are not attributed to the earlier CI's six-test baseline result.
