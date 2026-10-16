import test from 'node:test';
import assert from 'node:assert/strict';
import { read } from './support.mjs';

test('STATIC: private/auth apps and session principals are absent', async () => {
  const source = await read('config/settings/base.py');
  assert.doesNotMatch(source, /["']django\.contrib\.(?:admin|auth|sessions)["']/);
  assert.match(source, /SENSITIVE_OPERATIONS_ENABLED = False/);
  assert.match(source, /CATALOG_READ_ONLY = True/);
  const urls = await read('config/urls.py');
  const routes = [...urls.matchAll(/path\("([^"]*)"/g)].map(m => m[1]);
  assert.deepEqual(routes, ['', 'fiqh', 'fiqh/nodes/<int:ident>', 'fiqh/nodes/<int:ident>/children',
    'healthz','readyz','api/v1/status','api/v1/fiqh/books','api/v1/fiqh/roots',
    'api/v1/fiqh/search','api/v1/fiqh/nodes/<int:ident>','api/v1/fiqh/nodes/<int:ident>/children','assets/<path:asset>']);
});
test('STATIC: method rejection and host checking occur before dispatch', async () => {
  const s = await read('config/middleware.py');
  assert.match(s, /request\.get_host\(\)/);
  assert.match(s, /request\.method not in \{"GET", "HEAD"\}/);
  assert.ok(s.indexOf('status=405') < s.indexOf('self.get_response(request)'));
  assert.match(s, /len\(request\.path_info\) > 2048/);
  assert.match(s, /QUERY_STRING.+> 4096/);
});
test('STATIC: edition and heading serializers whitelist public provenance', async () => {
  const s = await read('apps/reference/services.py');
  assert.doesNotMatch(s, /__dict__|model_to_dict|\.values\(\)|SELECT\s+\*|\.raw\(/i);
  assert.match(s, /"source_archive_sha256": edition\.source_archive_sha256/);
  assert.match(s, /"source_input_sha256": edition\.source_input_sha256/);
  assert.match(s, /"source_id": heading\.source_id/);
  assert.match(s, /"id": heading\.source_row_id/);
  assert.doesNotMatch(s, /"(?:input_name|ingest_checksum|title_normalized|ingested_at)"\s*:/);
});
test('STATIC: search uses ORM values without raw SQL or string SQL interpolation', async () => {
  const s = await read('apps/reference/services.py');
  assert.match(s, /filter\(title_original=value\)/);
  assert.match(s, /filter\(\*\*\{f"\{field\}__contains": token\}\)/);
  assert.doesNotMatch(s, /\.raw\(|\.extra\(|cursor\.execute|\.execute\(/);
});
test('STATIC: SSR original titles use default escaping and no safe override', async () => {
  for (const name of ['catalog_content.html','heading_list.html']) {
    const s = await read('templates/reference/' + name);
    assert.doesNotMatch(s, /\|\s*safe\b|autoescape\s+off|mark_safe/);
    assert.match(s, /\{\{ (?:node|item)\.title \}\}/);
  }
});
test('STATIC: browser title rendering uses textContent and no HTML parser sink', async () => {
  const s = await read('apps/reference/static/reference/catalog.js');
  assert.match(s, /node\.textContent = text/);
  assert.doesNotMatch(s, /\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write|eval\(|new Function/);
});
test('STATIC: restrictive HTMX policy, scope note, Arabic RTL and focus styles', async () => {
  const base = await read('templates/reference/base.html');
  assert.match(base, /lang="ar" dir="rtl"/);
  assert.match(base, /"allowEval":false,"allowScriptTags":false,"selfRequestsOnly":true/);
  assert.ok(base.includes('هذا فهرس مصدر واحد، وليس تصنيفًا عامًا للفتاوى'));
  assert.ok(base.includes('وليست فتاوى منشورة'));
  assert.match(await read('apps/reference/static/reference/catalog.css'), /:focus-visible\s*\{[^}]*outline:/);
});
test('STATIC: update/delete immutability and same-edition parent triggers are declared (not executed)', async () => {
  const sql = await read('apps/reference/migrations/0002_immutable_hierarchy.py');
  for (const table of ['referencework','referenceedition','referenceheading']) {
    assert.match(sql, new RegExp('BEFORE UPDATE OR DELETE\\s+ON reference_' + table));
  }
  assert.match(sql, /parent_edition <> NEW\.edition_id/);
  assert.match(sql, /parent_depth \+ 1 <> NEW\.depth/);
  assert.match(sql, /BEFORE INSERT/);
});
test('STATIC: internal edition retains exact input identity and ingest checksum', async () => {
  const models = await read('apps/reference/models.py');
  for (const field of ['input_name','ingest_checksum','source_archive_sha256','source_input_sha256','edition_key'])
    assert.match(models, new RegExp(field + ' = models\\.CharField'));
  const records = await read('apps/reference/records.py');
  assert.match(records, /input_name must be a logical basename/);
  assert.match(records, /ensure_ascii=False, sort_keys=True, separators=\(",", ":"\)/);
});
