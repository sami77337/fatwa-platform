import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { validateRegistry, validateSchema, verifySourceBytes, sourceLines, sha256, readContained } from '../validate.mjs';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const registry = JSON.parse(await readFile(new URL('../../../docs/product/feature_registry.json', import.meta.url), 'utf8'));
const schema = JSON.parse(await readFile(new URL('../../../docs/product/feature_registry.schema.json', import.meta.url), 'utf8'));
const mutate = (fn) => { const copy = structuredClone(registry); fn(copy); return copy; };
const feature = (r, id) => r.features.find((f) => f.id === id);

// Non-sensitive synthetic clause text exists only in memory. These fixtures do
// not replace the ignored owner exports or establish any product acceptance.
function syntheticOriginals() {
  const copy = structuredClone(registry);
  const lines = Array.from({length: 2275}, () => '');
  for (const item of copy.evidence.filter((e) => e.source_id === 'SPEC_TEXT')) {
    for (let line = item.start_line; line <= item.end_line; line += 1) lines[line - 1] = item.id + ' synthetic line ' + line;
    item.text_sha256 = sha256(lines.slice(item.start_line - 1, item.end_line).join('\n'));
  }
  const spec = Buffer.from(lines.join('\r\n'), 'utf8');
  const rows = copy.evidence.filter((e) => e.kind === 'CLAUSE').sort((a, b) => a.clause.index_line - b.clause.index_line).map((item) => ({id: item.id, unit: item.clause.unit, number: item.clause.number, start_line: item.start_line, end_line: item.end_line, text_sha256: item.text_sha256, verbatim: lines.slice(item.start_line - 1, item.end_line).join('\n'), source_id: 'S04', source_path: 'sources/04_product_spec.txt'}));
  const index = Buffer.from(rows.map((r) => JSON.stringify(r)).join('\n'), 'utf8');
  const bytes = new Map([['SPEC_TEXT', spec], ['CLAUSE_INDEX', index]]);
  for (const source of copy.sources) if (bytes.has(source.id)) source.sha256 = sha256(bytes.get(source.id));
  return {copy, bytes, rows};
}

function rejectMutation(name, fn, expected) {
  test(name, () => {
    const errors = validateRegistry(mutate(fn), schema);
    assert.ok(errors.length > 0, 'unsafe mutation must fail');
    if (expected) assert.match(errors.join('\n'), expected);
  });
}

test('derived registry has complete source coverage while all product checks remain NOT_RUN', () => {
  assert.deepEqual(validateRegistry(registry, schema), []);
  assert.equal(registry.evidence.filter((e) => e.kind === 'CLAUSE').length, 479);
  assert.equal(registry.features.length, 24);
  assert.equal(registry.features.flatMap((f) => f.acceptance_criteria).length, 93);
  assert.equal(registry.features.filter((f) => f.implementation.status === 'IMPLEMENTED_VERIFIED').length, 0);
});

test('schema distinguishes all eight requested classifications without fabricating records', () => {
  assert.deepEqual(schema.$defs.feature.properties.classification.enum, ['OWNER_APPROVED', 'OWNER_APPROVAL_PENDING', 'PROPOSED', 'SUPERSEDED', 'DEFERRED', 'OUT_OF_SCOPE', 'IMPLEMENTED_VERIFIED', 'UNKNOWN']);
  assert.equal(registry.features.filter((f) => f.classification === 'SUPERSEDED').length, 0);
});

for (const unit of ['U03', 'U10']) {
  rejectMutation(unit + ' cannot be approved through a narrower decision', (r) => {
    const item = feature(r, 'FR-' + unit);
    item.classification = 'OWNER_APPROVED'; item.owner_approval.status = 'OWNER_APPROVED';
    item.owner_approval.basis = 'REPOSITORY_DECISION_RECORD'; item.owner_approval.evidence_ids = ['MANDATE-D067'];
  }, /unit status changed/);
}
rejectMutation('generic encouragement cannot serve as an exact unit approval', (r) => {feature(r, 'FR-U09').owner_approval.evidence_ids = ['MANDATE-S6'];}, /unsupported unit approval basis/);
rejectMutation('a new invented unit cannot acquire documentary approval', (r) => {const added = structuredClone(feature(r, 'FR-U01')); added.id = 'FR-U17'; added.acceptance_criteria.forEach((c) => {c.id += '-NEW';}); r.features.push(added);}, /no exact approved source/);
rejectMutation('product approval cannot imply implementation verification', (r) => {feature(r, 'FR-D069').implementation.status = 'IMPLEMENTED_VERIFIED';}, /verification evidence is absent/);
rejectMutation('planned feature checks cannot claim PASS', (r) => {feature(r, 'FR-D069').acceptance_criteria[0].status = 'PASS';}, /planned checks/);
rejectMutation('S6 registry tests cannot become product-test evidence', (r) => {feature(r, 'FR-D069').test_status = 'PASS';}, /verification evidence is absent/);
rejectMutation('activation remains disabled', (r) => {feature(r, 'FR-D069').activation = 'ENABLED';}, /fixed value/);
rejectMutation('gate B cannot be cleared', (r) => {r.context.gates.B = 'PASS';}, /fixed value/);
rejectMutation('C D E and Phase01 remain held', (r) => {r.context.gates.C = 'PASS'; r.context.gates.D = 'PASS'; r.context.gates.E = 'PASS'; r.context.gates.Phase01 = 'READY';}, /fixed value/);
rejectMutation('historical permission rows confer no grants', (r) => {r.context.permission_binding = 'ACTIVE';}, /fixed value/);
rejectMutation('DOMAIN_TRANSACTION is no runnable principal', (r) => {r.context.domain_transaction_is_principal = true;}, /fixed value/);
rejectMutation('book 622 is neither global taxonomy nor published fatwas', (r) => {r.context.source_book.is_global_taxonomy = true; r.context.source_book.is_published_fatwa_corpus = true;}, /fixed value/);
rejectMutation('AI remains disabled in current work', (r) => {r.context.ai_enabled = true;}, /fixed value/);
rejectMutation('D068 external ChatGPT stays V2', (r) => {feature(r, 'FR-D068-V2').suggested_release_slice = 'AI_V1_LATER';}, /missing or widened/);
rejectMutation('D070 final design cannot enter current development', (r) => {feature(r, 'FR-D070').development_scope = 'READ_ONLY_DEV';}, /missing or widened/);
rejectMutation('sensitive workflows cannot join the read-only metadata slice', (r) => {feature(r, 'FR-U08').development_scope = 'READ_ONLY_DEV';}, /only book 622/);
rejectMutation('missing clause coverage cannot retain a 479 claim', (r) => {r.evidence = r.evidence.filter((e) => e.id !== 'SPEC-U03-048');}, /expected 479/);
rejectMutation('missing unit group cannot retain a 479 claim', (r) => {r.features = r.features.filter((f) => f.id !== 'FR-U10');}, /missing unit group/);
rejectMutation('duplicate IDs are rejected', (r) => {r.evidence.push(structuredClone(r.evidence[0]));}, /duplicate ID/);
rejectMutation('exact source pins cannot be silently replaced', (r) => {r.sources[0].sha256 = '0'.repeat(64);}, /pin mismatch/);
rejectMutation('source revisions and trust categories cannot be silently replaced', (r) => {r.sources[0].revision = 'OTHER'; r.sources[0].kind = 'REPOSITORY_MANDATE';}, /pin mismatch/);
rejectMutation('reversed line ranges are rejected', (r) => {r.evidence[0].end_line = r.evidence[0].start_line - 1;}, /reversed line range/);
rejectMutation('a changed clause number is rejected', (r) => {r.evidence[0].clause.number = '1.99';}, /misnumbered clause/);
rejectMutation('dangling evidence and dependency refs are rejected', (r) => {feature(r, 'FR-D069').evidence_ids.push('NO-SOURCE'); feature(r, 'FR-D069').dependencies.push('NO-DEPENDENCY');}, /dangling reference/);
rejectMutation('catalog source blockers cannot be omitted', (r) => {feature(r, 'FR-D069').dependencies = ['PUBLIC_BASELINE'];}, /required source/);
rejectMutation('criteria cannot borrow unrelated unit clauses', (r) => {feature(r, 'FR-U01').acceptance_criteria[0].source_evidence_ids = ['SPEC-U10-001'];}, /unrelated source/);
rejectMutation('owner feature removal is not chosen by this worker', (r) => {feature(r, 'FR-U12').owner_removal.status = 'REMOVED';}, /owner has not chosen/);
rejectMutation('supersession requires an actual newer decision', (r) => {feature(r, 'FR-RELEASE-PROPOSAL').classification = 'SUPERSEDED';}, /no exact superseding decision/);
rejectMutation('raw source payloads are not part of the derived registry', (r) => {r.evidence[0].verbatim = 'RAW SOURCE CONTENT';}, /unexpected property/);
rejectMutation('unknown classifications fail closed', (r) => {feature(r, 'FR-D069').classification = 'EXCELLENT';}, /unsupported value/);

test('schema rejects malformed types and unsupported schema keywords', () => {
  assert.ok(validateRegistry({...registry, features: null}, schema).some((e) => e.includes('wrong type')));
  assert.ok(validateSchema('x', {type: 'string', format: 'custom'}).some((e) => e.includes('unsupported schema keyword')));
});

test('synthetic originals verify normalized line anchors, IDs and text hashes', () => {
  const {copy, bytes} = syntheticOriginals();
  assert.deepEqual(verifySourceBytes(copy, bytes), []);
  assert.deepEqual(sourceLines(Buffer.from('\uFEFFa\r\nb')), ['a', 'b']);
});

test('changed original bytes fail their pin', () => {
  const {copy, bytes} = syntheticOriginals(); bytes.set('SPEC_TEXT', Buffer.from('changed'));
  assert.match(verifySourceBytes(copy, bytes).join('\n'), /SHA256 mismatch/);
});

test('clause locator/hash mismatch fails independently of whole-file SHA', () => {
  const {copy, bytes} = syntheticOriginals(); copy.evidence[0].start_line += 1;
  assert.match(verifySourceBytes(copy, bytes).join('\n'), /exact line range\/hash mismatch/);
});

test('false clause identity cannot pass through recomputed index SHA', () => {
  const {copy, bytes, rows} = syntheticOriginals(); rows[0].id = 'SPEC-U01-999';
  bytes.set('CLAUSE_INDEX', Buffer.from(rows.map((r) => JSON.stringify(r)).join('\n')));
  copy.sources.find((s) => s.id === 'CLAUSE_INDEX').sha256 = sha256(bytes.get('CLAUSE_INDEX'));
  assert.match(verifySourceBytes(copy, bytes).join('\n'), /identity\/locator mismatch/);
});

test('one supplied original cannot imply both were verified', () => {
  const {copy, bytes} = syntheticOriginals(); bytes.delete('SPEC_TEXT');
  assert.match(verifySourceBytes(copy, bytes).join('\n'), /required together/);
});

test('malformed JSONL returns a metadata-only error', () => {
  const {copy, bytes} = syntheticOriginals(); bytes.set('CLAUSE_INDEX', Buffer.from('{PRIVATE RAW PAYLOAD'));
  const errors = verifySourceBytes(copy, bytes);
  assert.match(errors.join('\n'), /invalid JSONL/); assert.doesNotMatch(errors.join('\n'), /PRIVATE RAW PAYLOAD/);
});

test('readContained rejects traversal beyond its explicit root', async () => {
  await assert.rejects(readContained(new URL('../', import.meta.url), '../../AGENTS.md'));
});

test('CLI uses explicit local evidence mode and fails on missing originals', () => {
  const result = spawnSync(process.execPath, ['tools/feature_registry/validate.mjs', '--source-dir', 'tools/feature_registry/tests'], {cwd: root, encoding: 'utf8'});
  assert.equal(result.status, 1); assert.match(result.stderr, /required file unavailable/); assert.doesNotMatch(result.stdout, /PINNED_ORIGINALS PASS/);
});

test('CLI rejects unknown or incomplete arguments without reading arbitrary inputs', () => {
  for (const args of [['--other'], ['--source-dir']]) {
    const result = spawnSync(process.execPath, ['tools/feature_registry/validate.mjs', ...args], {cwd: root, encoding: 'utf8'});
    assert.equal(result.status, 2); assert.match(result.stderr, /Usage:/);
  }
});
