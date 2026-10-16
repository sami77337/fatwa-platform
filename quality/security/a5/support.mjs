import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { request as nodeRequest } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export const root = fileURLToPath(new URL('../../../', import.meta.url));
export const origin = 'http://127.0.0.1:8000';
export const kind = 'SOURCE_BOOK_TOC_NOT_FATWAS';
export const pins = Object.freeze({
  archive: '82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce',
  input: '37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14',
  mapped: 'b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7',
});
export const headingKeys = ['id','source_id','parent_id','title','depth','position','source_order',
  'children_count','part','page','page_id','source_entry_number'].sort();
export const editionKeys = ['id','edition_key','title','publisher','heading_count','root_count',
  'max_depth','source_archive_sha256','source_input_sha256','work'].sort();
export const read = name => readFile(new URL('../../../' + name, import.meta.url), 'utf8');
export const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const sortObject = value => Array.isArray(value) ? value.map(sortObject) : value !== null && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sortObject(value[key])])) : value;
export const canonical = value => JSON.stringify(sortObject(value));
export const evidence = { origin, requests: 0, status_counts: {}, maximum_inflight: 1 };
let denialAllowed = false;
export async function request(route, { method = 'GET', headers = {} } = {}) {
  assert.ok(route.startsWith('/') && !route.startsWith('//'));
  const url = new URL(route, origin);
  assert.equal(url.origin, origin);
  assert.ok(['GET','HEAD'].includes(method) || denialAllowed, 'Denial probes require non-production preflight');
  // Raw Node HTTP preserves Host and TRACE, which Fetch filters/forbids.
  // Do not follow redirects or send cookies, credentials, bodies or external requests.
  const result = await new Promise((resolve,reject) => {
    const req = nodeRequest(url, {method,headers,signal:AbortSignal.timeout(10000)}, res => {
      const parts=[]; let bytes=0;
      res.on('data',chunk=>{bytes+=chunk.length;
        if(bytes>2*1024*1024)res.destroy(new Error('A5 response exceeds 2 MiB'));
        else parts.push(chunk);});
      res.on('error',reject);
      res.on('end',()=>resolve({status:res.statusCode,headers:new Headers(Object.entries(res.headers)
        .flatMap(([key,value])=>Array.isArray(value)?value.map(v=>[key,v]):value===undefined?[]:[[key,value]])),
        body:Buffer.concat(parts).toString('utf8')}));
    });
    req.on('error',reject); req.end();
  });
  evidence.requests++;
  evidence.status_counts[result.status] = (evidence.status_counts[result.status] ?? 0) + 1;
  return {...result,json() {return JSON.parse(result.body);}};
}
export function secure(response) {
  const csp = response.headers.get('content-security-policy') ?? '';
  for (const rule of ["default-src 'none'", "script-src 'self'", "connect-src 'self'", "object-src 'none'",
    "base-uri 'none'", "frame-ancestors 'none'", "form-action 'self'"]) assert.ok(csp.includes(rule), rule);
  assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval|https?:|\*/);
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(response.headers.get('x-frame-options'), 'DENY');
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('access-control-allow-origin'), null);
  assert.equal(response.headers.get('access-control-allow-credentials'), null);
  assert.equal(response.headers.get('set-cookie'), null);
}
export async function json(route, expected = 200) {
  const r = await request(route);
  assert.equal(r.status, expected, route + ': ' + r.body.slice(0,150));
  assert.match(r.headers.get('content-type') ?? '', /^application\/json\b/i);
  secure(r);
  const data = r.json();
  assert.equal(data.kind, kind);
  return data;
}
export async function preflight() {
  const middleware = await read('config/middleware.py');
  assert.match(middleware, /request\.method not in \{"GET", "HEAD"\}/);
  assert.ok(middleware.indexOf('status=405') < middleware.indexOf('self.get_response(request)'));
  const settings = await read('config/settings/base.py');
  assert.match(settings, /config\.middleware\.PublicReadOnlyMiddleware/);
  const status = await json('/api/v1/status');
  assert.equal(status.read_only, true);
  assert.equal(status.sensitive_write_routes_enabled, false);
  assert.equal(status.fatwa_publications_available, false);
  assert.equal(status.deployment, 'NOT_DEPLOYED');
  assert.equal(status.gates, 'GATES_HOLD');
  denialAllowed = true;
  return status;
}
export function heading(row) {
  assert.deepEqual(Object.keys(row).sort(), headingKeys, 'Public projection changed');
  assert.ok(Number.isSafeInteger(row.id) && row.id > 0);
  assert.match(row.source_id, /^622-[1-9][0-9]*$/);
  assert.equal(row.source_id, '622-' + row.id);
  assert.ok(typeof row.title === 'string' && row.title.length > 0 && row.title.length <= 500);
  assert.ok(Number.isInteger(row.depth) && row.depth >= 1 && row.depth <= 5);
  for (const key of ['position','source_order','page','page_id']) assert.ok(Number.isSafeInteger(row[key]) && row[key] > 0, key);
  assert.ok(Number.isInteger(row.children_count) && row.children_count >= 0);
  assert.ok(typeof row.part === 'string' && row.part.length > 0);
  assert.equal(row.parent_id === null, row.depth === 1);
  assert.ok(row.source_entry_number === null || Number.isSafeInteger(row.source_entry_number) && row.source_entry_number > 0);
}
export function page(data, limit, offset) {
  assert.equal(data.limit, limit); assert.equal(data.offset, offset);
  assert.equal(data.count, data.total);
  assert.ok(Number.isInteger(data.total) && data.total >= 0 && data.total <= 20000);
  assert.equal(data.items.length, Math.min(limit, Math.max(0, data.total - offset)));
  assert.equal(data.next_offset, offset + limit < data.total ? offset + limit : null);
  for (const row of data.items) heading(row);
}
export const mappedRecord = row => ({ source_id: row.source_id, source_row_id: row.id,
  parent_source_row_id: row.parent_id, source_order: row.source_order, position: row.position,
  depth: row.depth, source_page_id: row.page_id, source_part: row.part,
  source_page_number: row.page, title_original: row.title, source_entry_number: row.source_entry_number });
