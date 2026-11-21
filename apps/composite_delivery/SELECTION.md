# Explicit text-only delivery choice

Original owner point122, `SPEC-U01-023`, decisionD-060: a human may choose the
text component when the approved answer contains text and audio. The source
inventory remains unchanged. This is synthetic development functionality;
production transport and provider acceptance remain outside this proof.

## Behavior

`FATWA_COMPOSITE_CHOICES_ENABLED` defaults to literalFalse. When explicitly
enabled with the existing composite feature and an exact configured current
identity provider, the native case desk offers a confirmed **text-only preview**.
The preview lists every omitted audio/file/image/link and preserves the full
approved answer and manifest. Unsupported media never causes an implicit choice.
The human may return to the full preview before staging.

The selected plan retains the original full manifest hash but has its own
selection-aware part fingerprint. A full-answer approval signature cannot
authorize the selected plan. The existing independent signed approval, queue,
worker lease, provider receipt and audit chain are reused. The canonical decision
has one immutable `CompositeDelivery.selection_mode`: once staged, it cannot be
rebound as another choice to resend parts. Default callers and old ALL plans
retain their existing fingerprints.

All selected reads, staging, reservation, original resolution and outcome checks
re-evaluate current scholarly approval, facts, source scope and capabilities.
The selected path additionally requires the current configured identity object
or its authenticated RequestDirectory wrapper, and a pure identity epoch. Native
responses hold these pins through rendering. Changing the context rolls back a
mutation or denies its result.

Migration0003 adds the immutable choice field and its allowed-kind constraint.
The existing database binding guard verifies the full canonical decision and
manifest plus the selected one-text/available-audio relation. A schema downgrade
cannot erase a recorded text-only choice. The older migration-reversal test now
restores the latest app leaf after checking its original0001/0002 behavior.

## Evidence and remaining verification

- Existing composite/desk plus six initial selection methods:33/33 PASS on real
  PostgreSQL17 and18. This includes actual signed delivery of one selected part,
  idempotency across a fresh database connection, original preservation,
  independent signatures, immutable history, CSRF and late revocation.
- Final selected contracts, including configured-provider substitution and
  recovery:8/8 PASS per PostgreSQL major. PG17 7.215s; PG18 7.095s. These overlap
  the previous run and are not summed as independent coverage.
- Fresh recovery helper: `apps.composite_delivery.selection_recovery` restores
  the populated existing answer/queue tables. It verifies the signed historical
  provider receipt with a supplied public verification key only; it does not
  recreate private signing keys, current grants, rows or audit events. Four
  denial reads cover disabled selection, absent identity provider, absent
  capabilities and revoked current reader, followed by a positive read. Both
  omitted original files retain their exact content hashes.
- Protected native journey:
  `apps.composite_delivery.browser_selection.CompositeChoiceBrowserTests.test_native_explicit_text_selection_preserves_audio_and_requires_independent_signed_plan`.
  It selects in the actual form, downloads and signs the exact selected fixture
  plan, stages and imports the actual provider fixture response, checks the
  unchanged audio, proves scope revocation, and records320/1280 screenshots and
  a browser trace at
  `.local/qa/functional-continuation/composite-choice-browser/result.json`.
  **Hosted execution and the integrated encrypted restoration drill are pending.**

No external send, read-confirmation claim, automatic retry or production grant
is added by this feature. GateB NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
NOT_DEPLOYED. This file does not itself credit a completed original requirement.
