# FAST8 case permission context

Development-only, deny-only adapter over `editorial_queue.build_queue_catalog`
and `policy_gap_engine.evaluate` (which delegates to `permission_lab.evaluate`).
No new authorization rules, models, URLs, database access or mutations.

The missing function was a binding between a hypothetical permission decision
and an exact queue case. The existing permission lab deliberately contains no
case IDs. This adapter issues immutable scalar-only receipts, then rebuilds the
fixed synthetic queue to check the receipt before and after policy evaluation.

Receipts contain the exact case key, batch, external ID, payload SHA-256, row
source SHA-256, source offsets/ordinal/kind, fixture label and a full row snapshot
SHA-256. The snapshot includes existing revisions, timestamps, references and
CSV overflow metadata. It detects stale state even when intake bytes did not
change. Unicode and CRLF are never normalized; nothing changes in source data.

Source meanings are explicit:

- Original intake: SHA of the exact synthetic payload and original UTF-8 row slice.
- Prepared CSV/JSON/JSONL: SHA of original batch bytes, plus the queue's **parsed
  field serialization** hash. This is not claimed to be an original byte slice.
- History: existing intake serialization, not an owner source file.

Duplicate external IDs are rejected across the complete queue, including all
copies of `W7-VALID-1` and cross-batch `SYN-SHARED`. No external-ID joins, aliases,
case folding or fallback selection exist. Blocked rows and missing/invalid IDs
cannot produce a usable receipt. Pending rows may be described as case context;
the description does not claim a draft, verified reference or accepted intake.

`scenario_resource` must be an existing lab resource. It is an **explicit
hypothesis**, not a mapping from queue status or an assertion that the case has
the hypothetical resource/state. Changing the hypothesis is a different query,
never a permission grant. `case_key` is supplied independently when evaluating,
so a complete receipt for another case is rejected. Receipts are not secrets,
signatures, capabilities or protection against changing trusted Python code.

Every returned decision has `effect=DENY` and `allowed=false`, fixed fields that
cannot be supplied to the dataclass constructor. Independent statuses:

- `context_status=VERIFIED`: exact fresh synthetic identity only.
- `REJECTED`: invalid, duplicate, blocked, stale or substituted context.
- `NOT_CONNECTED`: queue or pinned policy contract unavailable.
- `policy_status=POLICY_PENDING`: U03/U10 remain pending owner acceptance.
- `evidence_status=MISSING_EVIDENCE`: original policy clauses, historical rows
  and owner acceptance are unavailable, even when synthetic hashes verify.

The existing engine's candidate reasons and target-state checks are preserved.
An internal effect remains non-callable; workflow compatibility is not access.
Unknown caller identifiers and raw input are never echoed in reports.

See [CLI instructions](../../tools/fast8_case_permission/README.md).

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED; U03/U10 OWNER_APPROVAL_PENDING. Owner archives NOT_SUPPLIED;
owner-source acceptance NOT_RUN. This lane adds no browser or DB functionality.
