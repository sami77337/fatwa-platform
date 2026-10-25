# Permission laboratory implementation plan

Goal: execute exact hypothetical actor/action/resource inspection with a permanent
DENY result and useful reasons, connected to a guarded Arabic development UI.
Spec: the user's FAST5 permission lane instruction. Base: FAST4 `262fa3d`.

Architecture: reuse the S3 inert validator and synthetic fixtures byte-for-byte,
with explicit provenance and integrity pins, because these are not integrated in
FAST4. Reuse FAST4's pure Wave7 review transitions and local-only UI guard.
No database, session, authentication, role assignment or write operations.

The 70 historical rows, 58 transitions and full U03/U10 clauses are unavailable.
Never reconstruct them or treat synthetic fixture coverage as historical coverage.

- [x] Source adapter: `sources.py`, pinned `upstream/` snapshot and source integrity
  tests. Missing or changed inputs must fail closed.
- [x] Pure service: immutable catalog/decision records; exact identifiers only;
  explicit synthetic action/resource bindings; workflow targets from existing
  contracts. Tests cover candidate metadata, pending policies, internal effects,
  actor spoofing, malformed identifiers, cross-resource matches and all states.
- [x] UI: guarded GET/HEAD-only view, form, reasons, provenance and gates;
  duplicate/unknown/partial parameters rejected, no caller paths or records.
  One additive `config/urls.py` include. Tests include remote/production denials.
- [x] Run new and directly affected tests, lint and Django checks; record actual
  commands, fixture hashes and limitations in `README.md`.
- [x] One independent final review: PASS, no findings; independently reran 27 tests.
- [x] Prepare isolated FAST5 branch for commit/push and one draft PR to FAST4
  integration. External delivery identifiers are recorded in the final report.

Review focus: hierarchy must not imply access; internal effects must not become
actors; source failures must not look authorized; malformed inputs must not be
normalized into valid combinations; real/private identifiers must never load data.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD; NOT_DEPLOYED.
