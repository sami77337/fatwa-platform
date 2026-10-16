// Read-only acceptance of the existing real catalog. No Docker or database writes.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { inflateRawSync } from 'node:zlib';
import path from 'node:path';
import { locations, pins, root, checkHttp } from './host.mjs';

const inputSha = '37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14';
const originalSha = '13edc878f0b81d178c104bc976c4fe0d3970d8a1ef8bae26d6101f22ebbcd1a9';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const report = { timestamp: new Date().toISOString(), mode: 'READ_ONLY_CONFIRMATION',
  LIVE_SOURCE_CATALOG: 'NOT_RUN', scope: 'Pinned source and live ORM-backed HTTP; no direct SQL execution by this verifier.' };

function member(zip, wanted) {
  let end = zip.length - 22;
  while (end >= Math.max(0, zip.length - 65557) && zip.readUInt32LE(end) !== 0x06054b50) end--;
  assert.ok(end >= 0, 'Missing ZIP directory');
  let offset = zip.readUInt32LE(end + 16);
  for (let i = 0; i < zip.readUInt16LE(end + 10); i++) {
    assert.equal(zip.readUInt32LE(offset), 0x02014b50);
    const length = zip.readUInt16LE(offset + 28);
    const name = zip.subarray(offset + 46, offset + 46 + length).toString('utf8');
    if (name === wanted) {
      const local = zip.readUInt32LE(offset + 42);
      const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
      const bytes = zip.subarray(start, start + zip.readUInt32LE(offset + 20));
      const method = zip.readUInt16LE(offset + 10);
      assert.ok(method === 0 || method === 8);
      return method === 8 ? inflateRawSync(bytes, { maxOutputLength: 16 * 1024 * 1024 }) : bytes;
    }
    offset += 46 + length + zip.readUInt16LE(offset + 30) + zip.readUInt16LE(offset + 32);
  }
  throw Error('Pinned member missing');
}

function csv(text) {
  const rows = []; let row = [], value = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') { value += '"'; i++; }
      else quoted = !quoted;
    } else if (!quoted && (c === ',' || c === '\n')) {
      row.push(value.replace(/\r$/, '')); value = '';
      if (c === '\n') { rows.push(row); row = []; }
    } else value += c;
  }
  if (value || row.length) { row.push(value.replace(/\r$/, '')); rows.push(row); }
  assert.equal(quoted, false, 'Unclosed original-title CSV field');
  return rows;
}
const sorted = value => Array.isArray(value) ? value.map(sorted) :
  value !== null && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
const canonical = (spec, records) => sha(JSON.stringify(sorted({ schema: 1, spec, records })));
const record = item => ({ source_id: item.source_id, source_row_id: item.id,
  parent_source_row_id: item.parent_id, source_order: item.source_order, position: item.position,
  depth: item.depth, source_page_id: item.page_id, source_part: item.part,
  source_page_number: item.page, title_original: item.title, source_entry_number: item.source_entry_number });

async function get(route) {
  const response = await fetch('http://127.0.0.1:8000' + route,
    { method: 'GET', redirect: 'error', signal: AbortSignal.timeout(15000) });
  assert.equal(response.status, 200, route);
  const body = await response.json();
  assert.equal(body.kind, 'SOURCE_BOOK_TOC_NOT_FATWAS');
  return body;
}
async function main() {
  try {
    report.code_sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, windowsHide: true, encoding: 'utf8' }).trim();
    report.working_tree_modified = Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: root, windowsHide: true, encoding: 'utf8' }).trim());
    const zip = await readFile(locations.archive);
    assert.equal(sha(zip), pins.archive, 'Archive SHA256 mismatch');
    const prefix = 'FATWA_622_FIQH_COMPLETE/';
    const input = member(zip, prefix + '622_الفهرس_كامل_11397.jsonl');
    const originals = member(zip, prefix + '622_العناوين_الأصلية_ID_title.csv');
    assert.equal(sha(input), inputSha);
    assert.equal(sha(originals), originalSha);
    const rows = input.toString('utf8').trimEnd().split('\n').map(line => JSON.parse(line));
    const [header, ...originalRows] = csv(originals.toString('utf8').replace(/^\uFEFF/, ''));
    const idColumn = header.indexOf('title_id'), titleColumn = header.indexOf('original_title');
    assert.ok(idColumn >= 0 && titleColumn >= 0);
    const titles = new Map(originalRows.map(row => [Number(row[idColumn]), row[titleColumn]]));
    assert.equal(originalRows.length, 11397); assert.equal(titles.size, 11397);
    const expected = rows.map((row, index) => ({ id: row.id, source_id: row.lucene_title_key,
      parent_id: row.parent_id, title: row.title, depth: row.depth, position: row.position_among_siblings,
      source_order: index + 1, children_count: row.children_count, part: String(row.source_part),
      page: row.source_page_number, page_id: row.source_page_id, source_entry_number: row.source_entry_number }));
    assert.equal(new Set(expected.map(row => row.id)).size, 11397);
    for (const row of rows) assert.equal(row.title, titles.get(row.id), 'Original ID/title differs');
    const manifest = JSON.parse(await readFile(path.join(root, 'docs/data-ingest/owner-622-r1-jsonl.manifest.json'), 'utf8'));
    const spec = { source_namespace: 'shamela', source_book_id: '622', work_title: 'كشاف القناع عن متن الإقناع',
      madhhab: 'حنبلي', edition_key: '622-moj-owner-r1-20261011', edition_title: manifest.edition,
      publisher: 'وزارة العدل السعودية', source_archive_sha256: pins.archive, source_input_sha256: inputSha,
      input_name: '622_الفهرس_كامل_11397.jsonl', expected_rows: 11397, expected_roots: 32, expected_max_depth: 5 };
    assert.equal(canonical(spec, expected.map(record)), pins.mapped, 'Source mapping checksum differs');
    const books = await get('/api/v1/fiqh/books?limit=100');
    assert.equal(books.total, 1, 'Unexpected catalog snapshot');
    const edition = books.items[0];
    assert.equal(edition.edition_key, spec.edition_key);
    assert.equal(edition.title, spec.edition_title);
    assert.equal(edition.publisher, spec.publisher);
    assert.equal(edition.source_archive_sha256, pins.archive);
    assert.equal(edition.source_input_sha256, inputSha);
    assert.deepEqual(edition.work, { source_namespace: spec.source_namespace, source_book_id: '622',
      title_original: spec.work_title, madhhab: spec.madhhab });
    const groups = new Map();
    for (const row of expected) { if (!groups.has(row.parent_id)) groups.set(row.parent_id, []); groups.get(row.parent_id).push(row); }
    for (const group of groups.values()) group.sort((a, b) => a.position - b.position);
    assert.equal(groups.get(null).length, 32);
    const actual = new Map(); let requests = 0;
    const jobs = [...groups.entries()]; let next = 0;
    async function consume() {
      while (next < jobs.length) {
        const [parent, children] = jobs[next++];
        let offset = 0;
        do {
          const route = parent === null ? '/api/v1/fiqh/roots' : '/api/v1/fiqh/nodes/' + parent + '/children';
          const page = await get(route + '?edition=' + edition.id + '&limit=100&offset=' + offset); requests++;
          assert.equal(page.total, children.length, 'Actual child count differs');
          assert.equal(page.items.length, Math.min(100, children.length - offset));
          assert.deepEqual(page.items, children.slice(offset, offset + 100), 'Stored original fields/parents/order/pages differ');
          for (const item of page.items) { assert.ok(!actual.has(item.id), 'Repeated catalog row'); actual.set(item.id, item); }
          const wantedNext = offset + 100 < children.length ? offset + 100 : null;
          assert.equal(page.next_offset, wantedNext); offset = page.next_offset;
        } while (offset !== null);
      }
    }
    await Promise.all(Array.from({ length: 3 }, consume));
    assert.equal(actual.size, 11397);
    const depths = {};
    for (const row of rows) {
      const chain = []; let node = actual.get(row.id); const seen = new Set();
      while (node) {
        assert.ok(!seen.has(node.id) && seen.size < 5, 'Invalid live parent chain'); seen.add(node.id); chain.unshift(node);
        node = node.parent_id === null ? null : actual.get(node.parent_id);
        if (chain[0].parent_id !== null) assert.ok(node, 'Missing live parent');
      }
      assert.deepEqual(chain.map(item => item.id), row.path_ids, 'Live path IDs differ');
      assert.deepEqual(chain.map(item => item.title), row.path_titles, 'Live path titles differ');
      assert.equal(actual.get(row.id).children_count, groups.get(row.id)?.length ?? 0);
      depths[row.depth] = (depths[row.depth] ?? 0) + 1;
    }
    const liveChecksum = canonical(spec, [...actual.values()].sort((a,b) => a.source_order - b.source_order).map(record));
    assert.equal(liveChecksum, pins.mapped, 'Live mapped checksum differs');
    const probes = [1, 2, 5].map(depth => {
      const row = rows.find(item => item.depth === depth);
      const { position, source_order, children_count, ...probe } = actual.get(row.id);
      return { ...probe, path: row.path_ids };
    });
    report.http = await checkHttp({ edition_id: edition.id, _probes: probes });
    report.http.scope = 'All 11,397 live records, exact original fields, every parent path, 32 roots, depth 5, paging, search, SSR and denied writes. Browser checks recorded separately.';
    const ready = await get('/readyz'); assert.equal(ready.database_reachable, true);
    report.LIVE_SOURCE_CATALOG = 'PASS';
    report.source = { archive_sha256: pins.archive, input_member: prefix + '622_الفهرس_كامل_11397.jsonl',
      input_sha256: inputSha, mapped_checksum: liveChecksum,
      exact_original_id_title_matches: actual.size, roots: groups.get(null).length, max_depth: Math.max(...expected.map(row => row.depth)),
      depth_counts: depths, paged_catalog_requests: requests };
    // Host evidence is optional; the current HTTP/source check stands on its own.
    let prior = {};
    try { prior = JSON.parse(await readFile(path.join(root, '.local/host-result.json'), 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (prior.REAL_SOURCE_DATABASE_IMPORT === 'PASS' && prior.worker?.after?.preview?.checksum === liveChecksum) {
      report.previous_host_database_evidence = { timestamp: prior.timestamp, code_sha: prior.code_sha,
        result: 'PASS', import_action: prior.worker.import_action, database: prior.worker.after.database,
        role: prior.worker.after.role, server_version_num: prior.worker.after.server_version_num,
        counts: prior.worker.after.counts, unchanged_preview: prior.worker.after.preview.unchanged,
        tests: Object.fromEntries(Object.entries(prior.worker.tests).map(([key, value]) => [key, value.result])) };
    }
  } catch (error) { report.LIVE_SOURCE_CATALOG = 'FAIL'; report.blocker = error.message; }
  await mkdir(path.join(root, '.local'), { recursive: true });
  await writeFile(path.join(root, '.local/live-verification.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
  process.exitCode = report.LIVE_SOURCE_CATALOG === 'PASS' ? 0 : 1;
}
await main();
