import test from "node:test";
import assert from "node:assert/strict";
import { createDjangoAdapter } from "../../../apps/reference/static/reference/django-api.mjs";
const edition = { id: 7, edition_key: "ui-test-v1", title: "طبعة اختبار", publisher: "ناشر اختبار", work: { source_namespace: "synthetic", source_book_id: "test-ui", title_original: "مرجع اختبار", madhhab: "اختبار" }, heading_count: 26, root_count: 1, max_depth: 2, source_archive_sha256: "a".repeat(64), source_input_sha256: "b".repeat(64) };
const row = (id, parent = null) => ({ id, parent_id: parent, depth: parent ? 2 : 1, title: "عنوان عربي", position: id * 10, source_id: "test-" + id, children_count: parent ? 0 : 25, part: "المقدمة", page: 4, page_id: 400 });
function adapterWith(change = value => value) {
  return createDjangoAdapter({ origin: "http://localhost", editionId: 7, fetchImpl: async href => {
    const url = new URL(href); const inventory = url.pathname.endsWith("books"), children = url.pathname.endsWith("children");
    const value = { kind: "SOURCE_BOOK_TOC_NOT_FATWAS", edition, total: children ? 25 : 1, offset: children ? 20 : 0, limit: children ? 20 : 100, next_offset: null, parent: children ? 1 : undefined, items: inventory ? [edition] : children ? [22, 23, 24, 25, 26].map(id => row(id, 1)) : [row(1)] };
    return new Response(JSON.stringify(change(value, url)), { headers: { "Content-Type": "application/json" } });
  } });
}
test("gapped original positions are preserved while ARIA uses page ordinals", async () => {
  const adapter = adapterWith(); await adapter.catalog(); const page = await adapter.children("1", { cursor: "20" });
  assert.equal(page.offset, 20); assert.equal(page.items[0].position, 219); assert.equal(page.items[0].sibling_ordinal, 21); assert.equal(page.items.at(-1).sibling_ordinal, 25); assert.equal(page.items[0].sibling_total, 25);
});
test("same hash with changed scholarly attribution is rejected", async () => {
  const adapter = adapterWith((value, url) => url.pathname.endsWith("children") ? { ...value, edition: { ...edition, work: { ...edition.work, source_book_id: "different" } } } : value);
  await adapter.catalog(); await assert.rejects(adapter.children("1"), error => error.code === "INVALID_PAYLOAD");
});


test("D4 serializes only selected typed filters and preserves exact whitespace", async () => {
  const requests = [];
  const adapter = adapterWith((payload, url) => { requests.push(url); return payload; });
  await adapter.catalog();
  await adapter.search("  عنوان عربي  ", { mode: "exact" });
  assert.equal(requests.at(-1).searchParams.has("depth"), false);
  assert.equal(requests.at(-1).searchParams.has("has_children"), false);
  for (const depth of [1, 2, 3, 4, 5]) for (const hasChildren of [true, false]) {
    await adapter.search("  عنوان عربي  ", { depth, hasChildren });
    assert.equal(requests.at(-1).searchParams.get("depth"), String(depth));
    assert.equal(requests.at(-1).searchParams.get("has_children"), String(hasChildren));
    assert.equal(requests.at(-1).searchParams.get("q"), "  عنوان عربي  ");
  }
  for (const options of [{ depth: 0 }, { depth: 6 }, { depth: "2" }, { hasChildren: "false" }]) {
    const count = requests.length;
    await assert.rejects(adapter.search("عنوان", options), error => error.code === "INVALID_QUERY");
    assert.equal(requests.length, count);
  }
});
