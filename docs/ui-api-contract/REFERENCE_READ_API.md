> Integration note: this is the original S2 proposal. The running Django code uses
> [the reconciled actual S0 contract](INTEGRATED_DJANGO.md), not these proposed URLs.

# Proposed S2 public reference read contract for S0

Issue #3. **PROPOSAL / NON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD.**
These are documented requests for future S0 implementation, not live Django endpoints. No change to foundation files is included.

The catalog represents the table of contents of one Hanbali reference work. It is not an approved global fatwa taxonomy, published fatwa answers, complete book text, or a user/case repository. Book 622 and its Ministry of Justice edition must be pinned by the reviewed source ingest, rather than inferred from the UI's synthetic IDs.

## Requests

Base path proposed: `/api/reference/v1/`. Same origin only. GET with `Accept: application/json`; no credentials, redirects, write methods, or bearer tokens. Search and children request `limit=20`; the client rejects pages above 20. Server cursors are opaque, bounded strings tied to the query/root/source version and must be validated by S0. Offset-like cursors are an implementation detail of the mock.

| Method/path | Parameters | Result |
| --- | --- | --- |
| GET `catalog` | none | schema version, source, totals, exactly 30 book roots and two introduction roots |
| GET `nodes/{id}/children` | `limit=20`, optional `cursor` or `anchor_id` | one ordered page of direct children |
| GET `nodes/{id}` | none | node and its ordered ancestor trail including itself |
| GET `search` | `q`, `limit=20`, optional `root_id`, `cursor` | one ordered page of public title matches |

Node IDs are opaque ASCII letters/digits/underscore/hyphen, 1–100 characters. The prototype never puts titles into path segments. Paths and query values are encoded.

`anchor_id` and `cursor` are mutually exclusive. An anchored child request returns the page containing that direct child, with previous/next cursors. It allows revealing a deep search result using at most one paged request per ancestor, rather than downloading or sequentially scanning all siblings. Unknown or unrelated anchors fail. S0 may negotiate a different bounded reveal interface before integration.

## Public node

Every node has exactly the following renderable projection; extra properties are dropped by the client:

```json
{
  "id": "fixture-00003",
  "parent_id": null,
  "root_id": "fixture-00003",
  "kind": "book",
  "title": "كتاب تجريبي ١",
  "depth": 1,
  "position": 2,
  "child_count": 24,
  "has_children": true,
  "source": {
    "work_id": "synthetic-622",
    "work_title": "مرجع فقهي حنبلي تجريبي",
    "edition": "طبعة مصطنعة لا تمثل طبعة المصدر",
    "madhhab": "حنبلي",
    "synthetic": true,
    "printed_part": 1,
    "printed_page": 3
  }
}
```

This sample is synthetic. Never present its part/page as a citation to the real edition.

`kind` is one of `book`, `introduction`, `heading`; no fatwa kind. Depth is 1–5. Position is zero-based within the complete sibling set, preserving source order across pages. Root positions are within the full 32-root source order; the single-root UI presents that chosen root as position 1 of 1. `child_count` is the complete direct-child count and must agree with `has_children`. Leaves at depth five cannot have children. A root has null parent and `root_id=id`; other nodes are headings and have a parent.

Source work ID, title, edition, madhhab and synthetic flag must be source-pinned and consistent across roots and pages. Printed part and page are positive integers or explicit `null` if unavailable. The UI displays an Arabic unavailable label for null. Preserve original source title strings; apply normalization only to search keys.

Titles/edition/work labels are capped at 500 characters; IDs at 100; cursors at 200. Counts/positions are bounded at 100,000. The client caps decoded JSON at 256 KiB and times out requests after eight seconds. These are client protections; S0 must separately bound queries, response sizes and costs.

## Envelopes

Catalog:

```json
{
  "schema_version": 1,
  "fixture_id": "s2-synthetic-11397-v1",
  "source": { "work_id": "synthetic-622", "work_title": "مرجع فقهي حنبلي تجريبي", "edition": "طبعة مصطنعة لا تمثل طبعة المصدر", "madhhab": "حنبلي", "synthetic": true },
  "totals": { "nodes": 11397, "roots": 32, "books": 30, "max_depth": 5 },
  "books": ["30 public node objects"],
  "introductions": ["2 public node objects"]
}
```

The array strings above are placeholders in documentation; real responses contain public node objects. For a reviewed non-fixture source, `fixture_id` must be null and `synthetic` false.

Children and search pages:

```json
{
  "items": [],
  "total": 0,
  "next_cursor": null,
  "previous_cursor": null
}
```

Node detail is `{"node": PUBLIC_NODE, "breadcrumbs": [ROOT, ..., PUBLIC_NODE]}`. The trail includes the target and is capped at five nodes. IDs, root IDs, depths and parent edges must form a consistent ordered path. No answer text, requester field, user object, workflow, permissions, or account information belongs in these payloads.

## Search and error semantics

- Trim input. Require 2–120 Unicode characters both before and after normalization. Treat search as literal text, never a regular expression or SQL fragment.
- The mock normalizes Unicode compatibility forms, Arabic vowel marks, tatweel, alef variants and alef maqsura in search keys. It leaves original titles unchanged. S0 needs a reviewed equivalent normalization policy, bounded query plan and stable ordering.
- Optional `root_id` scopes a search to one of the 32 roots. A cursor must preserve the exact query, scope and source identity. UI pagination keeps the captured query/scope even if the form later changes.
- Return 200 with an empty page for no matches or an existing leaf. Unknown nodes: 404. Invalid query/limit/cursor/anchor: 400. Service failure: 5xx; bounded retry guidance can be added after review.
- JSON must use `application/json`. The client shows fixed Arabic error/retry text and never renders server error bodies or stack traces.
- Abort superseded requests. The view also checks request identity to reject late results when a transport ignores cancellation. Retry must retain the failed request's query/scope/cursor.
- Server must reject writes and deny private or unapproved content independently of this UI. Dropping unknown client fields is not a server authorization boundary.

## UI contract and integration limits

The default static demo uses no fetch requests for catalog/search; the in-memory mock exposes the same asynchronous interface. The full 11,397-node fixture stays in memory, while the DOM contains a chosen root and at most one expanded branch per level, with 20 siblings per page. Search has at most 20 result rows. Total mounted treeitems cannot exceed 81.

Tree keyboard behavior follows RTL directions: Left expands or enters the first child; Right collapses or enters the parent; Up/Down move visible items; Home/End move to the first/last visible item; Enter/Space toggle; Tab exits. Leaf nodes omit `aria-expanded`. Exactly one visible treeitem has tabindex zero. Parent groups contain direct child treeitems; paging controls remain outside the tree.

S0 must review this proposal before wiring templates/routes. No changes to Django, root dependencies, infrastructure, permissions or source ingest are part of S2. Source identity, real heading validation, PostgreSQL acceptance and browser/screen-reader checks remain separate required evidence. Gate B NOT_PASSED; Gates C/D/E HOLD; Phase01 BLOCKED; U03/U10 OWNER_APPROVAL_PENDING.
