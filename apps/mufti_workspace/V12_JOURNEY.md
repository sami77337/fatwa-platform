# V12 same-case journey controls

Base `742460a` includes independently reviewed P0. This slice changes only
`apps/mufti_workspace/**`; no new records, permissions, routes, settings or migrations.

## Usable changes

- The selected-case overview groups the original question, followups, source
  identifiers and private attachments by their existing Evidence version. It
  identifies facts newer than the latest answer's basis and lists the answer
  revisions based on each version. No acknowledgement or review event is invented.
- Image/audio/PDF previews are available directly inside that evidence history,
  using the existing authenticated private-file routes. Audio has `preload=none`,
  images/PDF use lazy loading, PDF stays sandboxed. Bytes remain in the existing
  immutable private storage; no server-side original I/O enters the frame context.
- The overview no longer offers a text-only draft save for an answer that has a
  multipart manifest. Its explicit edit handoff opens the existing multipart
  editor, whose retained-part selection preserves file hashes and old revisions.
  A disabled multipart editor offers no text-only fallback. This is UI guidance,
  not a new backend authorization rule.
- A keyboard-native journey menu opens current-case source/history, rights,
  research, citation, edit/review, availability, delivery and publication panels.
  All controls navigate; none submit approval, release, sending or provider
  reports. Disabled panels are absent, and pending clarification removes the edit
  shortcut. No completion percentage or delivery/access verification is inferred.

## Root integration contract

Existing context processor and header includes suffice. New selectors:
`#mufti-connected-journey`, `#mufti-evidence-history`,
`#mufti-evidence-{version}`, `[data-evidence-attachment]`,
`#mufti-multipart-edit`. Text-only drafts retain `#answer-text`; multipart drafts
use the existing `#multipart-text` after the handoff.

The shared publication handler may attach `request.publication_authorized_case_ref`
only after resolving the exact edition through its existing authorized service.
It is accepted on `pub_*` actions with matching posted case_ref; missing posted
case_ref is resolved only for `pub_open`/`pub_read`. The shared knowledge handler
may similarly attach `request.knowledge_authorized_case_ref` on `knowledge_*`
actions. A conflicting posted ref, conflicting resolved attributes or wrong action
fails closed. Every accepted selection rereads current staff scope and canonical
case state. These are server attributes, never request form/cookie capabilities.
Knowledge navigation marks the publication tab active. Root owns its publication
and knowledge handlers/templates and the library-return context; this slice does
not invent those actions or their source/material permission rules.

Add `apps.mufti_workspace.journey_tests` to the affected integrated verification.
No changes to P0 rights/expiry/admission/recovery boundaries are made.

## Focused evidence

- PostgreSQL17.12: initial **21/21 PASS** (6.156s), five new tests plus 16 existing
  workspace tests. Following exact publication-attribute compatibility review,
  **6/6 affected PASS** (2.227s), including the existing publication frame test.
- PostgreSQL18.7: final complete affected set **22/22 PASS** (6.769s).
- New checks exercise real private PNG/PDF/WAV bytes and scope revocation,
  evidence-version grouping, native multipart text edit retaining original file
  hashes/history, conflicting server/browser case refs and navigation without
  writes. Ruff and whitespace checks pass. Initial Ruff import-order warning was
  corrected before tests. No functional failure occurred.
- Protected Chrome and the full campaign are root-owned; no browser pass is
  claimed here. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED. No
  new progress estimate, real data, U03 grant, AI ruling or external send.
