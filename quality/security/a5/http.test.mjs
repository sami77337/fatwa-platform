import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { canonical, digest, editionKeys, evidence, heading, json, kind, mappedRecord,
  page, preflight, read, request, secure } from './support.mjs';
import { pins } from './support.mjs';

let edition, beforeInventory, allRows;
before(async () => {
  await preflight();
  beforeInventory = await json('/api/v1/fiqh/books?limit=100');
  assert.equal(beforeInventory.total, 1);
  edition = beforeInventory.items[0];
});
after(async () => {
  await writeFile(new URL('../../../docs/dev/a5/live-observations.json', import.meta.url),
    JSON.stringify({ timestamp: new Date().toISOString(), mode: 'ACTUAL_LOOPBACK_HTTP_NO_DIRECT_DB',
      ...evidence, edition, source_zip_independently_rehashed: false, direct_database_tests: 'NOT_RUN' }, null, 2) + '\n');
});
const route = (name, params = {}) => '/api/v1/fiqh/' + name + '?' + new URLSearchParams({edition: String(edition.id), ...params});
const expectedTitle = 'كشاف القناع عن متن الإقناع — طبعة وزارة العدل السعودية — الكتاب 622 في المكتبة الشاملة';

test('LIVE HTTP: liveness/readiness, non-production and disabled product boundaries', async () => {
  const h = await json('/healthz'); assert.equal(h.alive, true); assert.equal(h.read_only, true);
  const r = await json('/readyz'); assert.equal(r.database_reachable, true);
  // An ORM-backed HTTP readiness result is not a direct PostgreSQL test.
});
test('LIVE HTTP: one exact book-622 edition with immutable public provenance', async () => {
  assert.deepEqual(Object.keys(edition).sort(), editionKeys);
  assert.equal(edition.edition_key, '622-moj-owner-r1-20261011');
  assert.equal(edition.title, expectedTitle); assert.equal(edition.publisher, 'وزارة العدل السعودية');
  assert.equal(edition.heading_count, 11397); assert.equal(edition.root_count, 32); assert.equal(edition.max_depth, 5);
  assert.equal(edition.source_archive_sha256, pins.archive); assert.equal(edition.source_input_sha256, pins.input);
  assert.deepEqual(edition.work, {source_namespace:'shamela',source_book_id:'622',
    title_original:'كشاف القناع عن متن الإقناع',madhhab:'حنبلي'});
  assert.deepEqual((await json('/api/v1/fiqh/books?limit=100')).items, [edition]);
});
test('LIVE HTTP: public, missing and private routes reject every unsafe verb before dispatch', async () => {
  const routes = ['/fiqh','/api/v1/fiqh/books','/api/v1/fiqh/nodes/25','/admin/login/',
    '/api/v1/fatwas/publish','/api/v1/private/cases','/api/v1/ai/answer','/a5-missing'];
  for (const route of routes) for (const method of ['POST','PUT','PATCH','DELETE','OPTIONS','TRACE']) {
    const r = await request(route, {method});
    assert.equal(r.status, 405, method + ' ' + route); secure(r);
    assert.equal(r.headers.get('allow'), 'GET, HEAD');
    assert.match(r.headers.get('content-type') ?? '', /^application\/json/);
    assert.deepEqual(r.json(), {error:'method_not_allowed'});
  }
});
test('LIVE HTTP: cross-origin GET, CSRF-style POST and CORS preflight do not gain access', async () => {
  const origin = 'https://a5.invalid';
  const get = await request('/api/v1/fiqh/roots?limit=1', {headers:{Origin:origin,'Sec-Fetch-Site':'cross-site'}});
  assert.equal(get.status, 200); secure(get);
  // Public GET is allowed; absence of CORS opt-in is the relevant browser boundary.
  for (const method of ['POST','OPTIONS']) {
    const r = await request('/api/v1/fiqh/search', {method,headers:{Origin:origin,
      Referer:origin + '/test','Sec-Fetch-Site':'cross-site','Access-Control-Request-Method':'POST',
      'Access-Control-Request-Headers':'x-csrftoken,content-type'}});
    assert.equal(r.status, 405); secure(r);
    assert.equal(r.headers.get('access-control-allow-methods'), null);
  }
});
test('LIVE HTTP: private/auth/fatwa/AI/delivery/intake GET endpoints are absent', async () => {
  for (const route of ['/admin','/admin/','/admin/login/','/accounts/login/','/api/v1/users',
    '/api/v1/permissions','/api/v1/private/cases','/api/v1/intake','/api/v1/fatwas',
    '/api/v1/fatwas/1','/api/v1/fatwas/publish','/api/v1/ai/answer','/api/v1/telegram','/api/v1/whatsapp']) {
    const r = await request(route); assert.equal(r.status, 404, route); secure(r);
    assert.doesNotMatch(r.body, /Traceback|django\.db|password|requester|sessionid|csrfmiddlewaretoken/i);
  }
});
test('LIVE HTTP: negative, excessive and duplicate pagination/query values yield safe 400 JSON', async () => {
  const probes = ['limit=0','limit=101','limit=-1','limit=1.5','limit=1e2','limit=%D9%A1',
    'limit=999999999999999999999','offset=-1','offset=20001','offset=1%20OR%201%3D1',
    'edition=0','edition=9223372036854775808','edition=1&edition=1','limit=1&limit=2',
    'unexpected=1','callback=a5','format=jsonp'];
  for (const query of probes) {
    const p = await json('/api/v1/fiqh/roots?' + query, 400);
    assert.deepEqual(p, {kind,error:'invalid_query'});
  }
  for (const query of ['mode=regex','q=' + 'ا'.repeat(161), 'q=' + encodeURIComponent('كلمة '.repeat(11)),
    'q=%00','q=%0A','q=%7F','root=0','root=25&root=69'])
    await json('/api/v1/fiqh/search?' + query, 400);
  for (const query of ['anchor=0','anchor=-1','anchor=26&offset=0'])
    await json('/api/v1/fiqh/nodes/25/children?' + query, 400);
});
test('LIVE HTTP A5-003: too many query fields must retain the JSON API error contract', async () => {
  const query=Array.from({length:17},(_,index)=>'a'+index+'=1').join('&');
  const r=await request('/api/v1/fiqh/books?'+query);
  evidence.query_field_limit_error={fields:17,status:r.status,content_type:r.headers.get('content-type'),
    generic_error_without_diagnostics:!(/Traceback|TooManyFieldsSent|SECRET_KEY/.test(r.body))};
  assert.equal(r.status,400); secure(r);
  assert.doesNotMatch(r.body,/Traceback|TooManyFieldsSent|SECRET_KEY/);
  assert.match(r.headers.get('content-type')??'',/^application\/json\b/,
    'DATA_UPLOAD_MAX_NUMBER_FIELDS error escaped api_guard and returned an English HTML page');
  assert.deepEqual(r.json(),{kind,error:'invalid_query'});
});
test('LIVE HTTP: bounded pages, terminal offsets, leaves and missing edition/node errors', async () => {
  for (const limit of [1,30,100]) { const p = await json(route('roots',{limit})); page(p,limit,0); assert.deepEqual(p.edition, edition); }
  const end = await json(route('roots',{limit:100,offset:20000})); page(end,100,20000);
  for (const id of ['0','9223372036854775807','9223372036854775808','9'.repeat(100)])
    assert.deepEqual(await json(route('nodes/' + id),404), {kind,error:'not_found'});
  await json('/api/v1/fiqh/roots?edition=9223372036854775807',404);
});
test('LIVE HTTP: SQL-like strings and wildcard metacharacters are literal, bounded inputs', async () => {
  for (const q of ["' OR 1=1 --", "'; SELECT pg_sleep(5); --", '%', '_', "622-25' UNION SELECT 1--"])
    for (const mode of ['exact','literal','normalized']) {
      const p = await json(route('search',{q,mode,limit:1}));
      page(p,1,0); assert.equal(p.total,0, mode + ' ' + q); assert.equal(p.query,q);
    }
});
test('LIVE HTTP: reflected Arabic XSS search is escaped in SSR and JSON stays JSON', async () => {
  const q = 'عنوان <img src=x onerror=alert(622)> & "اختبار"';
  const r = await request('/fiqh?' + new URLSearchParams({q,basic:'1'}));
  assert.equal(r.status,200); secure(r);
  assert.ok(r.body.includes('&lt;img src=x onerror=alert(622)&gt;'));
  assert.ok(r.body.includes('&quot;اختبار&quot;'));
  assert.ok(!r.body.includes('<img src=x onerror=alert(622)>'));
  const data = await json(route('search',{q,mode:'exact'})); assert.equal(data.query,q); assert.equal(data.total,0);
  // This tests query reflection. Persisted malicious source titles are tested separately with synthetic responses.
});
test('LIVE HTTP: fake fatwa and personal-data canaries never become heading records', async () => {
  for (const q of ['A5_FAKE_FATWA_NEVER_SOURCE_622','A5_PRIVATE_CASE_20261015','a5-canary@example.invalid']) {
    const p = await json(route('search',{q,mode:'exact'}));
    assert.equal(p.total,0); assert.deepEqual(p.items,[]);
  }
});
test('LIVE HTTP: all 11,397 public records have only source fields and reproduce pinned content', async () => {
  const roots = await json(route('roots',{limit:100})); page(roots,100,0);
  assert.equal(roots.total,32);
  const queue = roots.items.filter(row => row.children_count > 0);
  const seen = new Map(roots.items.map(row => [row.id,row]));
  let pages = 1;
  for (let index=0; index<queue.length; index++) {
    const parent = queue[index]; let offset=0; const children=[];
    do {
      const p = await json(route('nodes/' + parent.id + '/children',{limit:100,offset})); pages++;
      page(p,100,offset); assert.equal(p.parent,parent.id); assert.equal(p.total,parent.children_count);
      assert.deepEqual(p.edition,edition); children.push(...p.items); offset=p.next_offset;
      assert.ok(pages < 20000,'Traversal request bound exceeded');
    } while (offset !== null);
    for (const row of children) {
      heading(row); assert.equal(row.parent_id,parent.id); assert.equal(row.depth,parent.depth+1);
      assert.ok(!seen.has(row.id),'Duplicated row'); seen.set(row.id,row);
      if (row.children_count > 0) queue.push(row);
    }
    for (let j=1; j<children.length; j++) assert.ok(children[j].position > children[j-1].position);
  }
  allRows=[...seen.values()].sort((a,b)=>a.source_order-b.source_order);
  assert.equal(allRows.length,11397); assert.equal(Math.max(...allRows.map(r=>r.depth)),5);
  assert.equal(new Set(allRows.map(r=>r.source_order)).size,11397);
  assert.equal(new Set(allRows.map(r=>r.source_id)).size,11397);
  for (const row of allRows) { const visited = new Set(); let current=row;
    while (current) { assert.ok(!visited.has(current.id) && visited.size < 5); visited.add(current.id);
      if (current.parent_id === null) break; current=seen.get(current.parent_id); assert.ok(current); }
    assert.equal(visited.size,row.depth);
  }
  const spec={source_namespace:'shamela',source_book_id:'622',work_title:'كشاف القناع عن متن الإقناع',
    madhhab:'حنبلي',edition_key:'622-moj-owner-r1-20261011',edition_title:expectedTitle,
    publisher:'وزارة العدل السعودية',source_archive_sha256:pins.archive,source_input_sha256:pins.input,
    input_name:'622_الفهرس_كامل_11397.jsonl',expected_rows:11397,expected_roots:32,expected_max_depth:5};
  const checksum=digest(canonical({schema:1,spec,records:allRows.map(mappedRecord)}));
  assert.equal(checksum,pins.mapped,'Public content/provenance differs from the pinned source mapping');
  const counts={}; for (const row of allRows) counts[row.depth]=(counts[row.depth]??0)+1;
  Object.assign(evidence,{all_heading_records:allRows.length,tree_pages:pages,depth_counts:counts,mapped_checksum:checksum,
    identity_comparison:'REPOSITORY_PIN_NOT_ORIGINAL_ARCHIVE_REHASH'});
});
test('LIVE HTTP: exact Arabic title, deep breadcrumb, leaf and anchored paging retain identity', async () => {
  assert.ok(allRows,'Exhaustive source traversal must pass first');
  const target=allRows.find(r=>r.depth===5); const byId=new Map(allRows.map(r=>[r.id,r]));
  const detail=await json(route('nodes/'+target.id)); assert.deepEqual(detail.node,target); assert.deepEqual(detail.edition,edition);
  const path=[]; for (let r=target;r;r=byId.get(r.parent_id)) path.unshift(r);
  assert.deepEqual(detail.ancestors,path);
  for (const mode of ['exact','literal','normalized']) {
    const search=await json(route('search',{q:target.title,mode,limit:100}));
    assert.ok(search.items.some(row=>row.id===target.id));
  }
  const leaf=await json(route('nodes/'+target.id+'/children')); page(leaf,30,0); assert.equal(leaf.total,0);
  const parent=byId.get(target.parent_id);
  const anchored=await json(route('nodes/'+parent.id+'/children',{anchor:target.id,limit:1}));
  assert.equal(anchored.items[0].id,target.id); assert.deepEqual(anchored.edition,edition);
  await json(route('nodes/25/children',{anchor:1}),404);
  await json(route('search',{q:'كتاب',root:target.id}),400);
});
test('LIVE HTTP: source IDs stay edition scoped and unknown route IDs never expose PK internals', async () => {
  const item=(await json(route('nodes/25'))).node;
  assert.equal(item.id,25); assert.equal(item.source_id,'622-25'); heading(item);
  await json('/api/v1/fiqh/nodes/25?edition=9223372036854775807',404);
  for (const query of ['pk=1','source_id=622-25','input_name=x','ingest_checksum=x'])
    await json('/api/v1/fiqh/nodes/25?' + query,400);
});
test('LIVE HTTP: error responses and HEAD retain CSP and omit internal diagnostics', async () => {
  const routes=['/api/v1/fiqh/roots?limit=101','/api/v1/fiqh/nodes/0','/a5-missing','/fiqh?mode=regex'];
  for (const route of routes) { const r=await request(route); assert.ok([400,404].includes(r.status)); secure(r);
    assert.doesNotMatch(r.body,/Traceback|OperationalError|ProgrammingError|PGPASSWORD|SECRET_KEY|C:\\Users|\/run\/secrets/); }
  for (const route of ['/healthz','/fiqh','/api/v1/fiqh/books','/api/v1/fiqh/nodes/0']) {
    const get=await request(route), head=await request(route,{method:'HEAD'});
    assert.equal(head.status,get.status); assert.equal(head.body,''); secure(head);
    assert.equal(head.headers.get('content-type'),get.headers.get('content-type'));
  }
});
test('LIVE HTTP: URI/query bounds and untrusted Host are rejected safely', async () => {
  const longPath=await request('/' + 'a'.repeat(2050)); assert.equal(longPath.status,414); secure(longPath);
  const longQuery=await request('/api/v1/fiqh/search?q=' + 'a'.repeat(4100)); assert.equal(longQuery.status,400); secure(longQuery);
  const host=await request('/healthz',{headers:{Host:'a5.invalid'}}); assert.equal(host.status,400); secure(host);
  assert.deepEqual(host.json(),{error:'invalid_host'});
});
test('LIVE HTTP: static allowlist denies raw source, fixtures, traversal and configuration', async () => {
  for (const route of ['/assets/reference/fixture.js','/assets/reference/api.js','/assets/reference/622.db',
    '/assets/reference/..%2f..%2fconfig%2fsettings%2fbase.py','/assets/reference/%5c..%5cAGENTS.md',
    '/assets/reference/../../AGENTS.md','/assets/django_htmx/../../AGENTS.md','/assets/.env',
    '/assets/reference/source.jsonl']) { const r=await request(route); assert.equal(r.status,404,route); secure(r); }
  for (const asset of ['catalog.js','django-api.mjs','catalog.css']) {
    const r=await request('/assets/reference/'+asset); assert.equal(r.status,200); secure(r);
    assert.match(r.headers.get('content-type'),asset.endsWith('css')?/^text\/css/:/^text\/javascript/);
    const local=await read('apps/reference/static/reference/'+asset);
    assert.equal(r.body.replaceAll('\r\n','\n'),local.replaceAll('\r\n','\n'),'Served code differs from reviewed code');
    assert.doesNotMatch(r.body,/createMockAdapter|from ["'].*fixture/);
    (evidence.served_asset_sha256??={})[asset]=digest(r.body);
  }
});
test('LIVE HTTP: HTML has RTL, labels, skip target, live status, source scope and basic fallback', async () => {
  const r=await request('/fiqh'); assert.equal(r.status,200); secure(r);
  assert.match(r.body,/<html lang="ar" dir="rtl">/); assert.match(r.body,/name="viewport"/);
  assert.ok(r.body.includes('هذا فهرس مصدر واحد، وليس تصنيفًا عامًا للفتاوى'));
  assert.ok(r.body.includes('وليست فتاوى منشورة')); assert.ok(r.body.includes('وزارة العدل السعودية'));
  const ids=[...r.body.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(new Set(ids).size,ids.length,'Duplicate HTML IDs');
  for (const match of r.body.matchAll(/<label\b[^>]*\bfor="([^"]+)"/g)) assert.ok(ids.includes(match[1]));
  for (const match of r.body.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
    assert.match(match[1],/\bsrc="\/assets\//); assert.equal(match[2].trim(),'');
  }
  const skip=r.body.match(/class="skip-link" href="#([^"]+)"/); assert.ok(skip); assert.ok(ids.includes(skip[1]));
  assert.match(r.body,/role="status" aria-live="polite"/);
  const basic=await request('/fiqh/nodes/25?basic=1'); assert.equal(basic.status,200);
  assert.ok(!basic.body.includes('reference/catalog.js')); assert.match(basic.body,/aria-current="page"/);
  assert.ok(basic.body.includes('622-25')); assert.ok(basic.body.includes('وزارة العدل السعودية'));
});
test('LIVE HTTP: full public edition and content snapshot remain unchanged after negative probes', async () => {
  const afterInventory=await json('/api/v1/fiqh/books?limit=100'); assert.deepEqual(afterInventory,beforeInventory);
  assert.deepEqual((await json(route('nodes/25'))).node,allRows.find(row=>row.id===25));
  evidence.public_snapshot_metadata_unchanged=true;
  // This observes public metadata and one row after probes. It is not direct DB mutation auditing.
});
