# Direct approved fatwa in owner-private research collections

This **additive** collection source captures an exact `AnswerRevision` that is
the **current approved answer of the same locked case**. It does not publish
fatwas, treat a draft as approved, confer CITE/EXPORT rights, grant another
case's answer, or infer a scholarly judgment.

- The native form is `research_collection_add_fatwa`, submitted only from
  the owner/browser-bound signed collection state. It does not accept a
  client-supplied source identifier, answer text, hash or decision. The server
  resolves the current approved answer in the existing casework transaction.
- The collection retains only a `Resource(kind="APPROVED_FATWA",
  identifier=answer UUID, sha256=answer text hash)` plus a private note. The
  complete answer text is never copied into the collection row.
- Opening a source requires the case remain in `ANSWERED`, the exact answer
  be the current `Case.approved_answer`, and evidence versions and SHA-256
  match. The historical slot becomes unavailable after editing or withdrawal
  rather than silently switching versions. Existing casework signed approvals,
  role/case scope and read privacy remain enforced.
- Independent `ResearchRights` `DISCOVER`/`READ_TEXT` still apply, with
  final policy epoch, identity and resource recheck on rendering/comparison.
  The external TOC/transcript `SourceRights` ledger does not own canonical
  case answers; the stock strict adapter accepts only this case-owned current
  approved-answer resource, and still denies all CITE/EXPORT privileges.
- Revocation hides source title, text and quoted private note, while preserving
  a removable collection slot. Other reference, transcript and knowledge
  types and their existing ledger checks are unchanged.
- Native CSRF + signed state + row revision + private owner scope are required,
  including for an empty/new collection. This is not a publication feature.

Three new PostgreSQL fixture cases in
`apps.research_workspace.test_collections` test the current approved answer,
stale draft/revocation/hidden note, strict external-ledger separation,
CSRF-bound native saving and forged source-state rejection.

**Still missing:** direct *lesson* and *book* collection source adapters with
their own source-use rights and exact version pins; cross-case/global fatwa
publication search; external provider proofs. This addition closes only the
same-case approved-fatwa segment of the relevant owner point, not the whole
fatwas/lessons/books requirement, and is not Gate B acceptance.
