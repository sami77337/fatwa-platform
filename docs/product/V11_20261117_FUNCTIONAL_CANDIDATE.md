# V11 functional candidate — synthetic rehearsal only

Base: PR #229, `0f90bb4f6c4ba426055fc77a3a783c2061d6ee19`.
Integration: `codex/20261117-v11-integration`; V10 is preserved.

**Gate B NOT_PASSED · C/D/E HOLD · Phase01 BLOCKED · NOT_DEPLOYED.**
The owner's 74% ±8 remains a historical engineering reference. This document
does not assign a new percentage, establish acceptance, authorize a real pilot,
approve scholarly content, or authorize deployment/public delivery.

## Connected changes

- The current-case Mufti desk shows the next action, current evidence, review
  blockers and human return reason. Its native tabs retain the canonical case
  through origin review, rights, research, multipart editing, private availability,
  delivery and independent publication. Recorded availability is not a live
  permission check or a delivery/read receipt.
- Requester clarification replies can save text and one permitted attachment as
  one atomic operation. Storage failure rolls back both; a new fact closes old
  answer availability. A temporary save notice is neither identity nor delivery.
- The source desk preserves raw Telegram/YouTube/website fixtures, idempotency,
  human correlation, immutable HOLD/REOPEN notes and filter context. Its simulator
  cannot add a real provider or infer identity from a display name.
- Exact source positions have case-scoped rights proposals, separate human
  review, expiry, correction and revocation. Registration/import/linkage alone
  grants nothing. READ, CITE, RELATE and PREVIEW_METADATA remain independent.
  Rights evidence in this rehearsal is a human-entered synthetic declaration,
  not proof of a real license. Book 622 remains a single book's TOC.
- Research searches authorized reference positions and linked transcript material,
  preserves the return position, and appends exact citations to the saved answer.
  Changing citations or the ordered file/audio parts creates a new answer version
  and requires fresh human approval. Original file bytes/history remain intact.
- The explicit local pilot workbench prepares the existing composite queue and
  accepts one human-selected fixture result per part. Separate ephemeral signing
  authorities simulate return permission and provider reports. Provider acceptance
  is not completed delivery; simulated completion is not real sending or reading.
  Failure, expiry or lost worker memory never triggers an automatic resend.
- Publication history and correction forms retain library filter context and the
  scoped case. Old form input is a copy-only buffer, never a fresh revision pin.
  Public-looking library preview still requires its separate exact, expiring
  preview policy as well as independent publication and current source rights.
- The recovery path uses durable ACTIVE/DRAINING/FROZEN admission and an explicit
  resume. V11 encrypts the whole bounded backup envelope with Fernet; keys live
  separately from repository/artifacts. Restored identities and verifiers must be
  explicitly reattached to the new database/private root before HTTP opens.

## Owner scope trace — closer to V1, not acceptance

Mapping uses the supplied 556-point owner scope and its 479 normalized clauses;
these are many-to-many mappings and must not be used as a completion denominator.

| Owner scope / clauses | V11 contribution | Remaining boundary |
| --- | --- | --- |
| 48–54, 489–490, 533; U02-001/004/006/008/011/037, U01-015 | Current-case daily desk and preserved evidence/source context | Human rehearsal and production identity policy remain unaccepted |
| 75–76; U02-012 | Multipart editing/reordering and local part-level outcomes | No external connector or real provider contract |
| 81–86; U01-017/018/019, U02-015/016/017 | Current-version human approval and independently confirmed simulated return | No AI approval; no real delivery/read claim |
| 501–504; U08-001/005/008/014/028 | Connected requester clarification/file flow and current answer availability | Real identity/recovery proofs are not invented |
| 532; U01-001/002/005 | Source fixtures, duplicate protection and human correlation history | WhatsApp/Facebook/Instagram stay closed |
| 536; U07-017, U09-012, U05-003 | Independent editorial publication and library return/history | Experimental gate only; no production publication |
| 543–556; U06 source/citation clauses, especially 554–556 | Exact-position rights and citations, retained original/edit distinction and audit | No full book corpus, generated quotation or inferred source rights |
| D031/D038 and U16-027 | Private originals, coordinated encrypted recovery and restored-target checks | Bounded synthetic drill; CI is not release acceptance |

The controlling decisions include D007/D016 (origins and versions), D031
(original media), D034/D035 (return versus publication), D037/D038 (access and
recovery), D047–D049 (connected staff/evidence/requester journey), D062 (precise
citations), D067 (unresolved U03 remains closed), D068 (human-reviewed citation
assistance, no automated fatwa), and D069 (622 TOC only).

## Actual parallel tasks

The parent supplied these running Codex thread identifiers and later verified
their remote commits. No task URL was available, so none is constructed here.

| Lane | Thread | Branch suffix / delivered SHA |
| --- | --- | --- |
| B requester | `6afc8096-82c4-8191-98d8-58fba73eb00c` | `v11-requester` / `278983fa93dda4c3e8d5b6b1614ae5fe2ab5b873` |
| C source rights | `6afc808d-03cc-8191-8171-3bfbe0ad201c` | `v11-source-rights` / `dd610e27d3bd08871259388801844519669f04f1` |
| D origin desk | `6afc807f-d7cc-8191-ad01-1d971f53f019` | `v11-source-desk` / `7e1ee09f6164ba2de8efdecaea0c79b88269dd92` |
| E recovery | `6afc9ae5-b338-8191-bcff-7654953230ed` | `v11-recovery` / `f1be973300e56ffd9f1360a566f014a0eeb78ddf` |
| F research | `6afc80af-d6a4-8191-a0ac-08f14e1b300b` | `v11-research` / `d8ecc7530ea512fe13ef403d8576cc90b6eaf756` |

All branch names have prefix `codex/20261117-`. Internal agents used isolated
worktrees for current-case presentation, publication navigation, local provider
simulation, rights enforcement, maintenance enforcement and the final browser
journey. Shared configuration/routing and cherry-picks have one integration owner.

## Run the manual rehearsal

Use the existing pinned Python environment and a PostgreSQL 17 or 18 binary
directory. The helper creates a disposable owned cluster; use synthetic files only.

```sh
python infra/dev/with_casework_postgres.py \
  --pg-bin /absolute/path/to/postgresql/17/bin --major 17 \
  --settings config.settings.campaign_review -- \
  python -m infra.dev.v11_demo
```

Append `--smoke` for a short startup/HTTP/freeze/resume check. The interactive
command prints temporary local credentials; do not copy them into evidence or
commit them. It seeds one source question and an unresolved followup, not an
answer, scholarly approval, rights approval, delivery intent or publication.
The primary Mufti proposes exact source rights; the separately scoped publisher
reviews them. Then use the case tabs to research, edit, review and explicitly
release the answer. The separate local simulator records only the part outcomes
chosen by the human. The private experimental library is usable; anonymous
preview remains closed until its independent exact policy is supplied.

The fixture expires, does not persist signing keys, and is deleted with its owned
runtime. Restart is not permission to reconstruct an interrupted provider attempt
or retry delivery. Recovery operations use the explicit CLI contract in
[`V11_CONTRACT.md`](../../apps/platform_recovery/V11_CONTRACT.md); there is no
production job, scheduler, automatic cutover or automatic maintenance resume.

## Evidence and limits

Local integration on PostgreSQL 17.12: **113 distinct functional/security tests
passed**, plus **16 encrypted recovery tests** and the manual startup smoke.
The functional batch first passed 112/113; the new navigation fixture omitted
its explicit web flag. Only that test was corrected and rerun successfully.
System checks, migration drift and changed-Python Ruff checks passed.

The final local connected Chromium 154 journey passed in 36.873 seconds with
`sandbox=False` explicitly recorded. It exercised one case, four evidence
versions, six answer revisions, the current two-part answer, an exact citation,
source-review history, independent rights/publication/knowledge approvals and
the existing two-part delivery queue. After encrypted restore, **56 HTTP
requests** each proved the target database and private root, exact PNG/WAV bytes,
native audio, current answer, signed simulation status and outsider/scope/rights
revocation denials. There were no external requests or page errors; 22 screenshots
cover RTL 320/1280. This is not a local sandboxed-browser or PG18 claim: those
checks are assigned to the exact-head CI matrix.

Browser attempt history is retained: an interrupted offscreen lazy-image wait;
pilot 409 subsequently diagnosed as `pilot_identity_changed` caused by the test
directory issuing a different expiry on each lookup; and a final queue-button
timeout whose original GET status was not recorded, so its cause remains
unproven. The fixture now uses a stable expiry, scrolls lazy media into view,
asserts navigation status and waits for the restored request-budget window to
expire naturally. No guard, counter or permission was weakened. A full journey
passed before that final timing change; only the affected journey was repeated
afterwards. The final wait preserved all four throttle rows without writing them.

The first CI head `3c67307619d2b3b473548c0b32a4ee0e68872940` passed the V11
PG17/18 matrix (113 functional + 16 recovery tests on each, sandboxed Chrome on
PG17). Four compatibility workflows failed and remain historical evidence:
three shared one outdated exact middleware-list expectation, corrected to require
the new outer maintenance guard and closed defaults; the V10 browser selected the
first citation form inside a closed supporting-tools `details` instead of the
visible case navigation. The latter was reproduced locally and diagnosed from
the actual DOM, then its navigation selector was corrected without changing the
product or skipping keyboard/status checks. The profile test also joins the V11
matrix. See the PR for final-head CI results; the initial failures are not flakes
or reclassified successes. A focused profile-test attempt outside the owned
runtime was correctly blocked with `WRITES_DISABLED`; it passed through the owned
PostgreSQL helper.

Lane receipts remain with their applications. Final integrated test results and
the tested SHA belong in the campaign PR/CI artifact; lane results alone cannot
establish that the assembled campaign works. Failed attempts remain historical
evidence and are not renamed as successful runs.

The maintenance gate is cooperative local process admission, not a PostgreSQL
superuser/OS security boundary. Raw SQL, uninstrumented ORM, unmanaged processes
and production/NFS workers are outside the supported rehearsal. Start all
participating processes with the same bound control directory; keep unsupported
writers and GC stopped. Source migration/bootstrap must finish before opening the
application. Missing control configuration must close the V11 composition.
Stock Django `flush`, `loaddata`, `clearsessions`, `dbshell` and `shell` are not
maintenance-aware administrative entrypoints: prohibit them against an active or
frozen V11 database. Test teardown uses its separately owned disposable database
only after the V11 application profile and its processes have stopped. Direct
database-owner access is not presented as a permission granted by this product.

Encrypted backup is bounded to 32 MiB captured file bytes / 64 MiB ciphertext,
held in memory, with no secure-memory-erasure or production KMS claim. V10's
legacy plaintext Python path remains explicitly legacy. A restore killed before
its nonce exists remains unknown and preserved; no guessed deletion is allowed.
Inspection can reconcile only an already matching nonce/owner/name before an
identity-checked rollback. Successful restore does not auto-cutover or resume.

Research's source-rights adapter denies case media by default until an explicit
media policy exists; existing separately authorized private case file controls
remain the way to inspect files. No malware scan is claimed without a scanner.
