# Organizer lesson linking

This development-only unit addresses owner point **95** and `SPEC-U03-012` using
the existing `LessonVersion`, `CaseLessonLink` and `LinkDecision` records. Actual
`ORGANIZER`/`ORGANIZER_ADMIN` identities propose, review, reject or withdraw links;
the same records remain readable by the existing Mufti scholarly-links service.
No identity is converted to MUFTI and no canonical scholarly boundary is widened.

## Explicit authority

`FATWA_OPERATIONAL_LESSON_LINKS_ENABLED` is false when absent and must be declared
false by integrating settings. The operational workspace and scholarly-links
features must also be enabled inside the owned synthetic development environment.

`READ_CASE` is required on both the fatwa case and the lesson's source case.
`READ_LESSON_LINKS` is an independent section grant for `lesson_links` on the
selected fatwa case. Six independent resource actions are available:

- `READ_OPERATIONAL_LESSON` — exact lesson version on its owning case.
- `READ_LESSON_LINK` — exact link and its lesson version.
- `PROPOSE_LESSON_LINK` — link the selected case to the exact lesson version.
- `APPROVE_LESSON_LINK`, `REJECT_LESSON_LINK`, `WITHDRAW_LESSON_LINK` — explicit
  review decisions on an exact existing link.

`CASE_LESSON_VERSION` resources contain `case_id`, `target_case_id`, `version_id`
and `version_sha256`. `CASE_LESSON_LINK` also includes `link_id` and `link_sha256`.
The existing configured `ScholarlyAuthority` must independently permit the same
current subject, endpoint pair, exact resource and corresponding domain action.
Neither layer replaces the other. All returns must be literal true, with the
operational grant deadline and both policy epochs checked again before response.

No role automatically receives any grant. The default has no policy. These
actions do not grant media bytes, lesson editing, series administration,
publication or any `RELATION` kind, including `REFERRED_BY_SHEIKH`, `DUPLICATE_OF`
or `SUPERSEDES`. Approving a lesson link does not approve a scholarly answer.

## Native behavior and source protection

The queue supplies a separate authorized lesson-link index, including completed
cases without changing pending-task counts. The native page lists authorized
lesson versions, permits a proposal against the current approved answer, accepts
an optional explicit recording span, and keeps review/withdrawal history visible.
Descriptive lessons work without a recording and cannot accept a fabricated
recording time. The page does not offer audio playback under a link-reading grant.

Only the existing immutable lesson-link/decision journals are appended. Source
questions, evidence, answers, approvals, recordings, metadata and lesson versions
remain unchanged. The private extracted persistence primitives retain the existing
replay, duplicate, hash-chain, transition and SQL invariants; their public Mufti
callers retain their original identity checks.

Strict forms reject client roles and unrelated fields. CSRF, exact hashes, source
and target revision/evidence pins, decision CAS, confirmation and command IDs
protect writes. Every replay rechecks current access. Old source links remain
historical and cannot acquire approval for a new answer; withdrawal keeps the
history. Removing either endpoint or the lesson/link read grant hides the card,
labels and derived list entry.

Sorted canonical/graph locks remain held through HTML rendering. The operational
watermark now includes lesson identities/versions, link journals, and existing
case relations/decisions. Authorized writes advance it by one exact row only.
The lesson adapter checks all consumed grants, then pins the policy object/epoch
and source-part metadata after callbacks. Late source changes, policy replacement,
expiry, revocation or render failure discard the page and roll back pending rows.

## Evidence integration

Behavior: `apps.operational_workspace.test_lesson_links`.

Recovery: `apps.operational_workspace.test_lesson_recovery`, with helper
`apps.operational_workspace.lesson_recovery_support`. It creates a live approved
link and a second withdrawn link through real services, verifies preserved review
history, performs 12 named denial checks under newly supplied current trust, then
actually rereads the positive projection and checks unchanged source/history pins.
`TABLES`, `FUNCTIONS`, `TRIGGERS` are empty: storage is already owned/registered by
scholarly links. No credentials or grants are stored in recovery pins.

Protected browser: one journey in
`apps.operational_workspace.browser_lessons.OperationalLessonsBrowserTests`.
Its result is `.local/qa/functional-continuation/operational-lessons-browser/result.json`,
with two actor traces and 320/1280 screenshots. Hosted execution of this exact
class is required before completion credit; this document asserts no browser pass.

## Limits

The current lesson corpus and recording used by evidence are explicitly synthetic.
This unit provides management of links to existing lessons, not a live scholarly
corpus, public lesson release or account-policy administration. D-054/D-067's
production policy details and release gates remain unchanged. Points 97 and 99
are outside this unit.
