// Explicitly opt-in, GET/HEAD only. Never imports, migrates, seeds, or writes.
// This probes the server at the supplied origin, which may be the unchanged source site.
import test from "node:test";
import assert from "node:assert/strict";

const configured = process.env.FATWA_A2_LIVE_ORIGIN;
const origin = configured ? new URL(configured) : null;
if (origin) assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname));
const live = configured ? test : test.skip;
const archive = "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce";
const input = "37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14";
const kind = "SOURCE_BOOK_TOC_NOT_FATWAS";
const prefix = "/api/v1/fiqh/";
async function read(route, expectedStatus = 200, method = "GET") {
  assert.ok(["GET", "HEAD"].includes(method));
  const url = new URL(route, origin);
  assert.equal(url.origin, origin.origin);
  const response = await fetch(url, { method, redirect: "error", credentials: "omit",
    cache: "no-store", signal: AbortSignal.timeout(8000) });
  assert.equal(response.status, expectedStatus, route);
  if (method === "HEAD") { assert.equal(await response.text(), ""); return response; }
  const data = await response.json();
  assert.equal(data.kind, kind);
  return data;
}
function source(edition) {
  assert.equal(edition.source_archive_sha256, archive);
  assert.equal(edition.source_input_sha256, input);
  assert.equal(edition.work.source_book_id, "622");
}
function page(data, limit) {
  source(data.edition);
  assert.ok(data.items.length <= limit);
  assert.equal(data.count, data.total);
  assert.equal(data.next_offset, data.offset + limit < data.total ? data.offset + limit : null);
}

live("source-pinned inventory and deterministic root pages without edition selection", async () => {
  const inventory = await read(prefix + "books");
  assert.equal(inventory.total, 1);
  source(inventory.items[0]);
  assert.equal(inventory.items[0].heading_count, 11397);
  assert.equal(inventory.items[0].root_count, 32);
  assert.equal(inventory.items[0].max_depth, 5);
  const all = await read(prefix + "roots?limit=100");
  page(all, 100);
  assert.equal(all.items.length, 32);
  const ids = [];
  for (let offset = 0; offset < 32; offset += 7) {
    const current = await read(prefix + "roots?limit=7&offset=" + offset);
    page(current, 7);
    ids.push(...current.items.map(row => row.id));
  }
  assert.deepEqual(ids, all.items.map(row => row.id));
  assert.equal(new Set(ids).size, 32);
});

// Samples read directly from the pinned original JSONL, not from generated fixtures.
const samples = [
  { id: 1, title: "مقدمة التحقيق", part: "المقدمة", page: 5, page_id: 2, path: [1] },
  { id: 2, title: "تقديم", part: "المقدمة", page: 5, page_id: 2, path: [1, 2] },
  { id: 8668, title: "النوع الثاني: تفويض المهر", part: "11", page: 504, page_id: 5459,
    path: [8550, 8551, 8665, 8667, 8668] },
  { id: 9709, title: "حكم المغيان الذي يقتل بعينه", part: "13", page: 218, page_id: 6230,
    path: [9693, 9694, 9700, 9708, 9709] },
];
live("original titles, printed references and shallow/five-level paths", async () => {
  for (const sample of samples) {
    const data = await read(prefix + "nodes/" + sample.id);
    source(data.edition);
    for (const key of ["title", "part", "page", "page_id"]) assert.equal(data.node[key], sample[key]);
    assert.equal(data.node.source_id, "622-" + sample.id);
    assert.deepEqual(data.ancestors.map(row => row.id), sample.path);
    assert.deepEqual(data.ancestors.map(row => row.depth), sample.path.map((_, i) => i + 1));
    assert.equal(data.ancestors[0].parent_id, null);
    for (let i = 1; i < data.ancestors.length; i++) {
      assert.equal(data.ancestors[i].parent_id, data.ancestors[i - 1].id);
    }
  }
});

live("anchors reveal late siblings and each ancestor of a fifth-level result", async () => {
  const late = await read(prefix + "nodes/2214/children?limit=20&anchor=2255");
  page(late, 20);
  assert.equal(late.offset, 40);
  assert.ok(late.items.some(row => row.id === 2255));
  for (const sample of samples.filter(row => row.path.length === 5)) {
    for (let i = 1; i < sample.path.length; i++) {
      const parent = sample.path[i - 1], child = sample.path[i];
      const data = await read(prefix + "nodes/" + parent + "/children?limit=20&anchor=" + child);
      page(data, 20);
      assert.ok(data.items.some(row => row.id === child));
      assert.ok(data.items.every(row => row.parent_id === parent));
    }
  }
});

live("source-aware exact, literal and normalized search and root scope", async () => {
  const sample = samples.find(row => row.id === 8668);
  for (const mode of ["exact", "literal", "normalized"]) {
    const query = new URLSearchParams({ q: sample.title, mode, root: "8550", limit: "20" });
    const data = await read(prefix + "search?" + query);
    page(data, 20);
    assert.ok(data.items.some(row => row.id === sample.id));
  }
  const other = await read(prefix + "search?" + new URLSearchParams({
    q: sample.title, mode: "exact", root: "25", limit: "20" }));
  assert.equal(other.total, 0);
  const first = await read(prefix + "search?q=" + encodeURIComponent("الصلاة") + "&root=69&limit=20");
  const next = await read(prefix + "search?q=" + encodeURIComponent("الصلاة") + "&root=69&limit=20&offset=20");
  page(first, 20); page(next, 20);
  assert.ok(first.total > 20);
  assert.equal(new Set([...first.items, ...next.items].map(row => row.id)).size,
    first.items.length + next.items.length);
});

live("invalid queries and unknown nodes have explicit read-only HTTP statuses", async () => {
  for (const route of ["roots?limit=101", "roots?limit=1&limit=2", "search?root=0",
    "search?q=x&root=2", "nodes/1/children?anchor=2&offset=0"]) await read(prefix + route, 400);
  for (const route of ["nodes/999999", "search?q=x&root=999999", "nodes/1/children?anchor=25"])
    await read(prefix + route, 404);
  await read(prefix + "nodes/8668", 200, "HEAD");
});

test("A2 candidate: empty search validates scope and basic navigation accepts anchors", {
  skip: !configured || process.env.FATWA_A2_EXPECT_PATCH !== "1",
}, async () => {
  await read(prefix + "search?q=&root=999999", 404);
  await read(prefix + "search?q=&root=2", 400);
  const response = await fetch(new URL("/fiqh/nodes/2214?basic=1&limit=20&anchor=2255", origin), {
    method: "GET", credentials: "omit", redirect: "error", signal: AbortSignal.timeout(8000) });
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.ok(html.includes("الأسير والمطمور بتحريان إذا اشتبهت الأشهر عليهما"));
  assert.ok(html.includes("offset=20") && html.includes("offset=60"));
});
