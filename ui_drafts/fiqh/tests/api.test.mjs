import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { createFixture, normalizeQuery, PAGE_SIZE } from "../fixture.js";
import { createMockAdapter, createReadOnlyAdapter, publicNode } from "../api.js";

const fixture = createFixture();
const mock = createMockAdapter({ fixture, delay: 0 });
const root = fixture.nodes.find(n => n.kind === "book");
const response = value => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
const live = fetchImpl => createReadOnlyAdapter("/api/reference/v1/", { origin: "http://127.0.0.1:4173", fetchImpl });
test("synthetic fixture: 11,397 unique headings / 32 roots / 30 books / depth 5", () => {
  assert.equal(fixture.nodes.length, 11397);
  assert.equal(fixture.byId.size, 11397);
  assert.equal(fixture.nodes.filter(n => !n.parent_id).length, 32);
  assert.equal(fixture.nodes.filter(n => n.kind === "book").length, 30);
  assert.equal(Math.max(...fixture.nodes.map(n => n.depth)), 5);
  for (const node of fixture.nodes) {
    assert.equal(node.source.synthetic, true);
    assert.equal(node.has_children, node.child_count > 0);
    if (node.parent_id) {
      const parent = fixture.byId.get(node.parent_id);
      assert.equal(parent.depth + 1, node.depth);
      assert.equal(parent.root_id, node.root_id);
      assert.equal(fixture.children.get(parent.id)[node.position].id, node.id);
    }
  }
});
test("catalog returns 30 books and 2 introductions without all descendant nodes", async () => {
  const catalog = await mock.catalog();
  assert.equal(catalog.books.length, 30);
  assert.equal(catalog.introductions.length, 2);
  assert.equal(catalog.totals.nodes, 11397);
  assert.ok(!("nodes" in catalog));
});
test("children are lazy and paged, with reversible opaque cursor handling", async () => {
  const first = await mock.children(root.id);
  assert.equal(first.items.length, PAGE_SIZE);
  assert.equal(first.total, 24);
  assert.equal(first.previous_cursor, null);
  const second = await mock.children(root.id, { cursor: first.next_cursor });
  assert.equal(second.items.length, 4);
  assert.equal(second.next_cursor, null);
  assert.deepEqual((await mock.children(root.id, { cursor: second.previous_cursor })).items, first.items);
});
test("anchored sibling page reveals search hit without loading all intervening nodes", async () => {
  const target = fixture.children.get(root.id)[23];
  const page = await mock.children(root.id, { anchorId: target.id });
  assert.ok(page.items.some(n => n.id === target.id));
  assert.equal(page.items.length, 4);
  assert.equal(page.previous_cursor, "0");
  await assert.rejects(mock.children(root.id, { anchorId: target.id, cursor: "0" }), /INVALID_CURSOR/);
  await assert.rejects(mock.children(root.id, { anchorId: root.id }), /NOT_FOUND/);
});
test("detail returns the exact parent trail at depth five", async () => {
  const leaf = fixture.nodes.find(n => n.depth === 5);
  const detail = await mock.node(leaf.id);
  assert.equal(detail.breadcrumbs.length, 5);
  assert.equal(detail.breadcrumbs[0].id, root.id);
  assert.equal(detail.breadcrumbs.at(-1).id, leaf.id);
});
test("Arabic search normalizes marks and alef without mutating original titles", async () => {
  assert.equal(normalizeQuery("إِخْتِبَار ـ آ"), "اختبار ا");
  const before = root.title;
  const result = await mock.search("كِتَاب", { rootId: root.id });
  assert.ok(result.total > 20);
  assert.equal(result.items.length, 20);
  assert.ok(result.items.every(n => n.root_id === root.id));
  assert.equal(root.title, before);
  assert.equal((await mock.search("عبارة غير موجودة إطلاقًا")).total, 0);
});
test("invalid query, cursor, root and unknown node fail explicitly", async () => {
  assert.throws(() => mock.search(" "), /INVALID_QUERY/);
  assert.throws(() => mock.search("َِ"), /INVALID_QUERY/);
  assert.throws(() => mock.search("ــ"), /INVALID_QUERY/);
  assert.throws(() => mock.search("س".repeat(121)), /INVALID_QUERY/);
  await assert.rejects(mock.children(root.id, { cursor: "-1" }), /INVALID_CURSOR/);
  await assert.rejects(mock.children(root.id, { cursor: "999999" }), /INVALID_CURSOR/);
  await assert.rejects(mock.node("absent"), /NOT_FOUND/);
  await assert.rejects(mock.search("كتاب", { rootId: fixture.children.get(root.id)[0].id }), /INVALID_ROOT/);
});
test("mock responses are copies and cannot mutate the fixture", async () => {
  const page = await mock.children(root.id);
  page.items[0].source.edition = "changed";
  page.items[0].title = "changed";
  const fresh = await mock.children(root.id);
  assert.notEqual(fresh.items[0].title, "changed");
  assert.notEqual(fresh.items[0].source.edition, "changed");
});
test("aborted lazy requests reject instead of delivering stale data", async () => {
  const controller = new AbortController();
  const pending = createMockAdapter({ fixture, delay: 50 }).children(root.id, { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});
test("public projection drops unknown private fields and rejects fatwa content", () => {
  const privateMarker = `synthetic-private-${randomUUID()}`;
  const projected = publicNode({ ...root, requester_email: privateMarker, answer: "synthetic-answer", source: { ...root.source, secret: privateMarker } });
  assert.ok(!JSON.stringify(projected).includes(privateMarker));
  assert.ok(!("answer" in projected));
  assert.throws(() => publicNode({ ...root, kind: "fatwa" }), /INVALID_PAYLOAD/);
  assert.throws(() => publicNode({ ...root, has_children: false }), /INVALID_PAYLOAD/);
});
test("read-only adapter rejects cross-origin and ambiguous API bases", () => {
  const embeddedCredentials = new URL("http://127.0.0.1:4173/api/");
  embeddedCredentials.username = "synthetic-user";
  embeddedCredentials.password = randomUUID();
  for (const base of ["https://external.example/api/", embeddedCredentials.href, "/api?x=1", "/api/#fragment", "file:///api/"]) {
    assert.throws(() => createReadOnlyAdapter(base, { origin: "http://127.0.0.1:4173" }), /UNSAFE_API_BASE/);
  }
});
test("integration requests are GET-only, credential-free, bounded and URL-encoded", async () => {
  const calls = [];
  const adapter = live(async (url, options) => { calls.push({ url, options }); return response(await mock.search("كتاب", { rootId: root.id })); });
  const page = await adapter.search("كتاب", { rootId: root.id });
  assert.equal(page.items.length, 20);
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.redirect, "error");
  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get("q"), "كتاب");
  assert.equal(url.searchParams.get("limit"), "20");
  assert.equal(url.searchParams.get("root_id"), root.id);
  assert.deepEqual(Object.keys(adapter).sort(), ["catalog", "children", "node", "search"]);
});
test("integration adapter validates catalog, children, detail and anchored pages", async () => {
  const values = [await mock.catalog(), await mock.children(root.id), await mock.node(root.id)];
  const adapter = live(async () => response(values.shift()));
  assert.equal((await adapter.catalog()).books.length, 30);
  assert.equal((await adapter.children(root.id)).items.length, 20);
  assert.equal((await adapter.node(root.id)).node.id, root.id);
  const target = fixture.children.get(root.id)[23];
  let requestUrl;
  const anchored = live(async url => { requestUrl = new URL(url); return response(await mock.children(root.id, { anchorId: target.id })); });
  assert.ok((await anchored.children(root.id, { anchorId: target.id })).items.some(n => n.id === target.id));
  assert.equal(requestUrl.searchParams.get("anchor_id"), target.id);
});
test("integration adapter rejects wrong parents, roots, breadcrumb edges and oversize pages", async () => {
  const page = await mock.children(root.id);
  await assert.rejects(live(async () => response({ ...page, items: [{ ...page.items[0], parent_id: "wrong" }] })).children(root.id), /INVALID_PAYLOAD/);
  await assert.rejects(live(async () => response(page)).search("كتاب", { rootId: "wrong" }), /INVALID_PAYLOAD/);
  await assert.rejects(live(async () => response({ ...page, items: [...page.items, page.items[0]] })).children(root.id), /INVALID_PAYLOAD/);
  const detail = await mock.node(page.items[0].id);
  detail.breadcrumbs[1].parent_id = "wrong";
  await assert.rejects(live(async () => response(detail)).node(page.items[0].id), /INVALID_PAYLOAD/);
});
test("integration adapter rejects invalid JSON, wrong media type, HTTP errors and oversized streams", async () => {
  for (const supplied of [
    new Response("bad-json", { headers: { "content-type": "application/json" } }),
    new Response("{}", { headers: { "content-type": "text/html" } }),
    new Response("x", { status: 500 }),
    new Response("x".repeat(262145), { headers: { "content-type": "application/json" } }),
  ]) await assert.rejects(live(async () => supplied).children(root.id));
});
test("search is literal rather than treating user input as a regular expression", async () => {
  const page = await mock.search(".*");
  assert.equal(page.total, 0);
});

test("integration rejects source drift, impossible root/leaf shapes and out-of-order siblings", async () => {
  const catalog = await mock.catalog();
  const page = await mock.children(root.id);
  const drift = structuredClone(page);
  drift.items[0].source.edition = "different edition";
  const values = [catalog, drift];
  const adapter = live(async () => response(values.shift()));
  await adapter.catalog();
  await assert.rejects(adapter.children(root.id), /INVALID_PAYLOAD/);
  assert.throws(() => publicNode({ ...root, root_id: "wrong" }), /INVALID_PAYLOAD/);
  assert.throws(() => publicNode({ ...fixture.nodes.find(n => n.depth === 5), has_children: true, child_count: 1 }), /INVALID_PAYLOAD/);
  const reversed = { ...page, items: [...page.items].reverse() };
  await assert.rejects(live(async () => response(reversed)).children(root.id), /INVALID_PAYLOAD/);
});
