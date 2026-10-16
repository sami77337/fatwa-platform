// Opt-in, read-only HTTP/source checks. Never imports data or changes Docker.
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { inflateRawSync } from "node:zlib";
import { execFileSync } from "node:child_process";
import { createDjangoAdapter } from "../../../apps/reference/static/reference/django-api.mjs";
const origin = process.argv[2], archivePath = process.argv[3], reportPath = process.argv[4];
if (!origin || !archivePath) throw Error("Usage: node tests/integration/ui/live.mjs http://127.0.0.1:8000 ORIGINAL_ZIP [REPORT_PATH]");
assert.ok(["127.0.0.1", "localhost"].includes(new URL(origin).hostname));
const archiveSha = "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce";
const inputSha = "37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14";
const inputName = "FATWA_622_FIQH_COMPLETE/622_الفهرس_كامل_11397.jsonl";
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const report = { timestamp: new Date().toISOString(), code_sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8", windowsHide: true }).trim(), working_files: "A1 uncommitted edits over integrated baseline", scope: "Original ZIP identity plus sampled live API records and real frontend adapter. HTTP only; no SQL or Django test database.", tests: [] };
function member(zip, wanted) {
  let end = zip.length - 22;
  while (end >= Math.max(0, zip.length - 65557) && zip.readUInt32LE(end) !== 0x06054b50) end--;
  assert.ok(end >= 0); let offset = zip.readUInt32LE(end + 16);
  for (let i = 0; i < zip.readUInt16LE(end + 10); i++) {
    const length = zip.readUInt16LE(offset + 28), name = zip.subarray(offset + 46, offset + 46 + length).toString("utf8");
    if (name === wanted) { const local = zip.readUInt32LE(offset + 42), start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28); const bytes = zip.subarray(start, start + zip.readUInt32LE(offset + 20)); const method = zip.readUInt16LE(offset + 10); assert.ok(method === 0 || method === 8); return method === 8 ? inflateRawSync(bytes, { maxOutputLength: 16 * 1024 * 1024 }) : bytes; }
    offset += 46 + length + zip.readUInt16LE(offset + 30) + zip.readUInt16LE(offset + 32);
  }
  throw Error("Missing source member");
}
async function check(name, fn) { await fn(); report.tests.push({ name, result: "PASS" }); }
async function json(route) { const response = await fetch(origin + route, { redirect: "error", signal: AbortSignal.timeout(10000) }); assert.equal(response.status, 200); return response.json(); }
try {
  const archive = await readFile(archivePath); assert.equal(sha(archive), archiveSha); const input = member(archive, inputName); assert.equal(sha(input), inputSha);
  const original = input.toString("utf8").trimEnd().split("\n").map(line => JSON.parse(line)); assert.equal(original.length, 11397);
  report.source = { archive_sha256: archiveSha, input_member: inputName, input_sha256: inputSha, original_rows: original.length };
  await check("pinned original ZIP and JSONL identity", async () => {});
  const adapter = createDjangoAdapter({ origin }); const catalog = await adapter.catalog();
  await check("real source identity / 11,397 headings / 32 roots / 30 books and 2 introductions / depth 5", async () => {
    assert.equal(catalog.source.source_archive_sha256, archiveSha); assert.equal(catalog.source.source_input_sha256, inputSha); assert.equal(catalog.source.work.source_book_id, "622"); assert.equal(catalog.source.work.madhhab, "حنبلي");
    assert.deepEqual(catalog.totals, { nodes: 11397, roots: 32, max_depth: 5 }); assert.equal(catalog.books.length, 30); assert.equal(catalog.introductions.length, 2);
    assert.deepEqual([...catalog.books, ...catalog.introductions].map(row => Number(row.id)).sort((a,b) => a-b), original.filter(row => row.parent_id === null).map(row => row.id).sort((a,b) => a-b));
  });
  // Prefer a deep path whose ancestor sits beyond the first 20 siblings.
  const byId = new Map(original.map(row => [row.id, row]));
  const siblings = id => original.filter(row => row.parent_id === id).sort((a,b) => a.position_among_siblings - b.position_among_siblings);
  const deep = original.find(row => row.depth === 5 && row.path_ids.some(id => { const current = byId.get(id); return current.parent_id !== null && siblings(current.parent_id).findIndex(sib => sib.id === id) >= 20; })) ?? original.find(row => row.depth === 5);
  report.sample = { id: deep.id, path: deep.path_ids, title: deep.title };
  await check("depth-five original title, lineage, printed part/page and anchored sibling pages", async () => {
    const detail = await adapter.node(String(deep.id)); assert.equal(detail.node.title, deep.title); assert.deepEqual(detail.breadcrumbs.map(row => Number(row.id)), deep.path_ids);
    for (const node of detail.breadcrumbs) { const expected = byId.get(Number(node.id)); assert.equal(node.title, expected.title); assert.equal(node.source.printed_part, String(expected.source_part)); assert.equal(node.source.printed_page, expected.source_page_number); assert.equal(node.source.page_id, expected.source_page_id); assert.equal(node.source.source_id, expected.lucene_title_key); }
    for (let i = 1; i < deep.path_ids.length; i++) { const parent = String(deep.path_ids[i-1]), anchorId = String(deep.path_ids[i]); const page = await adapter.children(parent, { anchorId }); const selected = page.items.find(row => row.id === anchorId); const ordinal = siblings(Number(parent)).findIndex(row => row.id === Number(anchorId)) + 1; assert.equal(selected.sibling_ordinal, ordinal); assert.equal(selected.sibling_total, siblings(Number(parent)).length); }
  });
  await check("exact original Arabic search, scoped search, paging, empty result", async () => {
    const exact = await adapter.search(deep.title, { mode: "exact" }); assert.ok(exact.items.some(row => row.id === String(deep.id)));
    const scoped = await adapter.search(deep.title, { mode: "exact", rootId: String(deep.path_ids[0]) }); assert.ok(scoped.items.some(row => row.id === String(deep.id)));
    const first = await adapter.search("فصل"); assert.ok(first.next_cursor); const next = await adapter.search("فصل", { cursor: first.next_cursor }); assert.equal(next.offset, 20); assert.ok(next.items.every(row => !first.items.some(previous => previous.id === row.id)));
    assert.equal((await adapter.search("عنوانغيرموجودلاختبارالفهرسفقط")).total, 0);
  });
  await check("safe errors, HEAD and rejected mutation methods on existing read-only catalog", async () => {
    await assert.rejects(adapter.node("9999999"), error => error.code === "NOT_FOUND"); await assert.rejects(adapter.search("س".repeat(161)), error => error.code === "INVALID_QUERY");
    const status = await json("/api/v1/status"); assert.equal(status.read_only, true); assert.equal(status.sensitive_write_routes_enabled, false); assert.equal(status.fatwa_publications_available, false);
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) { const response = await fetch(origin + "/api/v1/fiqh/roots", { method, redirect: "error", signal: AbortSignal.timeout(10000) }); assert.equal(response.status, 405); assert.equal(response.headers.get("allow"), "GET, HEAD"); }
    const head = await fetch(origin + "/fiqh", { method: "HEAD" }); assert.equal(head.status, 200); assert.equal(await head.text(), "");
    const after = await json("/api/v1/fiqh/books"); assert.equal(after.items[0].heading_count, 11397); assert.equal(after.items[0].source_input_sha256, inputSha);
  });
  await check("live SSR baseline deep link remains reachable (does not validate unserved A1 templates)", async () => {
    const response = await fetch(origin + "/fiqh/nodes/" + deep.id + "?edition=" + catalog.source.id + "&basic=1"); assert.equal(response.status, 200); const html = await response.text(); assert.ok(html.includes(deep.title)); assert.ok(html.includes("المطبوعة") || html.includes("صفحة"));
  });
  const local = await readFile(new URL("../../../apps/reference/static/reference/catalog.js", import.meta.url)); const served = await fetch(origin + "/assets/reference/catalog.js").then(r => r.text());
  report.a1_assets_on_existing_site = sha(local) === sha(served);
  report.result = "PASS";
} catch (error) { report.result = "FAIL"; report.error = error.stack; process.exitCode = 1; }
if (reportPath) await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report, null, 2));
