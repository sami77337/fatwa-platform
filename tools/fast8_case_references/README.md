# Synthetic case reference dossier

Read-only, offline composition of the existing case packet, reference diagnostics,
research bridge and fiqh reading trail. Select a fixed synthetic **case key**, never
an external ID, question, inferred title, file, URL or owner archive.

```powershell
python -m tools.fast8_case_references --synthetic-fixtures-only --case intake-1
python -m tools.fast8_case_references --synthetic-fixtures-only --case history
python -m unittest discover -s tests/fast8_case_references -v
```

The CLI writes deterministic UTF-8 JSON to stdout. Exit 0 means every occurrence
has an exact technical catalog/trail match; 2 means a complete report with missing
or unresolved evidence (also used for argument errors); 1 means invalid input or a
failed contract. Exit 0 is **not scholarly acceptance or an official gate pass**.
There are no file/path/URL inputs, clocks, database defaults or write endpoints.

`apps.fast8_case_references.services.build_dossier(case_key,
synthetic_fixtures_only=True, trail=..., catalog=...)` returns immutable canonical
bytes, a SHA256 property and a fresh payload copy. Without explicit catalog or
trail contracts, verified upstream references remain `NOT_CONNECTED`. No Django
catalog is created implicitly. Existing bounded packet serialization limits apply.

Each occurrence preserves its ordinal, upstream status/reasons, original-source
digest/offsets and verification scope. A citation is emitted only after exact
research-bridge and complete reading-trail verification. Work title, edition key,
edition ID, source row, part/page and both source pins remain exact. Ambiguous,
invalid, missing or changed evidence closes citations and navigation. A reordered
catalog snapshot is harmless; reordered reference occurrences are rejected.
Unresolved/forbidden pointers retain their ordinal, source digest and reasons,
without exporting their raw values or activating a link. Missing references are
explicit. Raw source, questions, answers, clips and revision bodies are excluded.
Source bytes, CRLF, Unicode and existing timestamps are never rewritten; the
packet digest binds the complete upstream packet without disclosing its contents.

The topology's `reading_trail.current.source_id` and the reference map's
`verified_identity.source_id` belong to distinct existing synthetic adapters.
They are retained in their own provenance structures, not conflated. The join uses
the full exact work/edition/source pins and numeric row identity. Navigation
neighbors are context, not additional case reference occurrences.

## Inputs and limitations

- Base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (FAST7 PR #134).
- CLI topology: `fast7c-reading-trail-synthetic-v1`.
- Fixture SHA256: `b1abc9c56a6173f8c7c2f573af746aaee6140aaea58df26b6ffebd7803e12d98`.
- Fixed Wave7 intake SHA256:
  `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb`.
- Archive/input `a`/`b` pins are fabricated fixture assertions. Owner archives:
  `NOT_SUPPLIED`; no archive inspection or production acceptance is claimed.
- Prepared batch occurrences retain their existing unresolved evidence. The
  upstream reading trail supports exact `WorkbenchCase` only; a bridge-verified
  `PreparedCase` is reported `NOT_CONNECTED/prepared_case_trail_unsupported`.
- No UI route or database migration. Browser/PostgreSQL tests: `NOT_RUN` for this
  pure service/CLI change. Shared CI is untouched; it does not explicitly select
  the new lane suite. The integration coordinator must add that collection.

## Validation record

Python 3.13, installed Django 5.2.18, no dependency changes.
31 new tests pass, zero skips. Directly used pure contracts: 45 tests pass across
research bridge, fiqh trail services/boundaries and reference resolution.
Packet tests require Django settings: the first plain unittest invocation reported
`ImproperlyConfigured` at packet class setup; the 45 pure tests still ran. Packet
Eight packet tests then passed with an empty in-process `DATABASES` mapping, preventing any
database connection. No historical browser or database suite was rerun.

Two initial new-test fixture assumptions failed (forbidden reason and literal
CRLF were absent in the selected existing serialized rows). Explicit fabricated
negative fixtures now exercise both cases through the existing resolver and
packet contracts; the negative assertions remain enforced.

Independent read-only agent review approved the implementation with no blocking
findings and independently reproduced the initial 30 passing tests. Its coverage
note was addressed with one additional test that explicitly asserts the unsupported
prepared-case trail boundary after a controlled bridge result (not source acceptance).

Official gates unchanged: Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
SCOPE_DEVIATION_HOLD; NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.
