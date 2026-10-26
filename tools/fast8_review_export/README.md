# FAST8 offline internal-review evidence preview

The existing immutable editorial export explicitly excludes persisted review.
This adapter adds a **separate evidence preview** by running the existing fixed
`workflow_invariants` scenario and associating it with verified workbench packets.
It does not update the original export, invent review history, or claim scholarly
completion. No application registration, URL mount, database, migrations, browser,
network service or new dependencies are needed.

## Run

From the repository root, with the existing Python 3.13 dependencies:

```text
python -B -m apps.editorial_export export --synthetic-fixtures-only --output tools/fast8_review_export/demo-source
python -B -m tools.fast8_review_export preview --synthetic-fixtures-only --source-bundle tools/fast8_review_export/demo-source --scenario rehearsal --output tools/fast8_review_export/demo-preview
python -B -m tools.fast8_review_export verify --synthetic-fixtures-only --source-bundle tools/fast8_review_export/demo-source --scenario rehearsal --input tools/fast8_review_export/demo-preview
python -B -m unittest discover -s tests/fast8_review_export -p "test_*.py" -v
```

Every output directory must be new; existing directories are never reused.
Use another new directory for a second run and compare bytes. Input and output
must be separate, with no symlinks/reparse points in their paths. Invalid input,
production settings, tampering or filesystem failures return exit 1; argument
errors return exit 2. Errors omit source text and paths. A filesystem error while
writing can leave a partial new directory; verification rejects it. There is no
automatic deletion, overwrite or retry.

## Exact contracts and association

- `editorial_export.verify_export` verifies all four source files against this
  checkout's fixed services **before** JSON is parsed. Rehashed changed source
  manifests do not establish trust. Historical or uploaded exports are unsupported.
- `workflow_invariants.scenario` and `replay` own events, transitions, snapshots,
  and state hashes. Only `rehearsal`, `preparation` and `blocked` are accepted;
  there is no arbitrary event-file or external workflow-result input.
- Association requires exact `case_key`, external ID, input/source hashes,
  source byte offsets, reference identities and reference results. Initial
  replay history and intake must exactly match packet snapshots and prepared
  intake. External IDs, shared payload hashes or similar text are never joins.
- Missing association is `NOT_CONNECTED`; a missing initial snapshot is
  `UNAVAILABLE`. Both omit projected events and source content. Missing data
  does not count as acceptance. Prepared batch cases have no matching scenario.
- `rehearsal` associates `intake-7`: six internal-review attempts (four `APPLIED`,
  two `REJECTED`). The two preparation attempts are excluded from CSV rows, but
  their effects are preserved in subsequent before/after snapshots and original
  ordinals. No preparation event is relabeled as review.
- `preparation` associates `history` but produces zero review rows. `blocked`
  associates `intake-1` but lacks a draft snapshot: six review attempts are
  explicitly omitted and the snapshot remains `UNAVAILABLE`.

## Output and verification

`preview.json` contains the 20 original case keys, packet hashes, association
status, replay provenance, and the connected case's exact source representation
and review evidence. `review-events.csv` contains those same event objects as
JSON-valued cells using the existing exporter. Decode with `csv.reader` followed
by `json.loads` for each data cell. Formula-like text cannot become a leading
spreadsheet operator; Arabic Unicode, CRLF, whitespace, types and timestamps are
not normalized. These JSON files are offline artifacts, not inline HTML scripts.

`manifest.json` pins both preview payloads, all four original export files, the
scenario, canonical request hash and canonical replay-result hash. State hashes
are preserved verbatim from the workflow engine (record plus review state); they
are **not** packet hashes. Packet hashes retain the workbench serializer's trailing
newline convention. Verification regenerates every preview byte against the
original verified source and the explicit scenario, including the manifest.
Coordinated changes to a preview and its manifest are rejected. Hashes are
integrity checks, not signatures or external approval.

The preview distinguishes `APPLIED`, `REPLAY` and `REJECTED`; an accepted retry is
not another applied event. `REVIEWED_INTERNAL` is a synthetic technical label.
`review_conclusion` and `scholarly_decision` remain null. Persisted review remains
`NOT_CONNECTED`; owner workflow transitions remain `NOT_SUPPLIED`. Original
packets and their `persisted_review` fields remain byte-for-byte unchanged.

## Fixture identity and limits

Base: `92fa517ecdefe3f1a92a1ab145ff55943474df44` (Draft PR #134).
Only existing fabricated development fixtures are used: fixed workbench cases,
synthetic batch rows and `wave7-synthetic-toc`. These identities are synthetic and
do not attest to a user-owned archive or book 622 source acceptance.

At this base:

- Source report SHA256: `17d54614349d20488344d2c6d432823d1d8ecb46d34c90f68d129084458725e9`.
- Source manifest SHA256: `44f4d707fba4eb1e07545cfb640188fe76d55de848924b12773214332b1453d2`.
- Rehearsal input SHA256: `b5767b892b1fcaec3167dad4c3d3394ed01b8ce3c96a28ce750e2c8acb44ad41`.
- Rehearsal result SHA256: `ee7f21c849864210b15a1d513ce5c2f944e5e52b2608e2aeaad0e4de51663f53`.

Bounds and development-only guards reuse the existing exporter. No real/private
records or owner source archives are accepted. Local PostgreSQL/browser acceptance
is `NOT_RUN` for this offline adapter. Shared CI is unchanged; its pre-existing
explicit lists do not register this lane's new tests. The integration coordinator
must add the focused command above when combining adapters.

Local validation on Python 3.13.15 / Django 5.2.18, Windows:

- New focused suite: 28 passed, zero skips, including nine CLI subprocess tests.
- Directly affected contracts: 29 passed, zero skips with
  `python -B manage.py test tests.workflow_invariants.test_engine tests.editorial_workbench.test_packets tests.editorial_export.test_services --settings=config.settings.test --noinput --verbosity=1`.
- Ruff lint/format and `git diff --check` passed for the owned changes.
- One independent final implementation review found no actionable defects.

Remote SHA, Draft PR and actual B6/C6/D6 run results are recorded in the PR
handoff, not inferred from these local tests. Those workflows do not establish
owner-source acceptance or a change to the official gates.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING.
