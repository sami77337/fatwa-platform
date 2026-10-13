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

test('D072 separates first-release deferral from exact U10 acceptance and D068 planned V1', () => {
  const hadith = feature(registry, 'FR-U10');
  assert.equal(hadith.classification, 'DEFERRED');
  assert.equal(hadith.development_scope, 'DEFERRED');
  assert.equal(hadith.suggested_release_slice, 'HADITH_LIBRARY_POST_FIRST_RELEASE');
  assert.equal(hadith.owner_approval.status, 'OWNER_APPROVAL_PENDING');
  assert.equal(hadith.owner_approval.recorded_date, null);
  assert.equal(hadith.activation, 'DISABLED');
  assert.equal(hadith.owner_removal.status, 'NOT_DECIDED');
  assert.equal(hadith.evidence_ids.filter((id) => id.startsWith('SPEC-U10-')).length, 28);
  assert.equal(hadith.release_timing.excluded_from_first_release, true);
  assert.equal(hadith.release_timing.applies_to, 'ALL_28_U10_CLAUSES');
  assert.equal(hadith.release_timing.recorded_date, '2026-10-13');
  assert.deepEqual(hadith.release_timing.evidence_ids, ['TASK-D072', 'RECORD-D072']);
  const citations = feature(registry, 'FR-D068-V1');
  assert.equal(citations.suggested_release_slice, 'AI_V1_LATER');
  assert.equal(citations.owner_approval.status, 'OWNER_APPROVED');
  assert.equal(citations.activation, 'DISABLED');
  assert.ok(!citations.dependencies.includes('OWNER_U10'));
  assert.ok(!citations.dependencies.includes('HADITH_LIBRARY_SOURCE'));
});
for (const slice of ['V1_KNOWLEDGE', 'AI_V1_LATER', 'PUBLIC_CATALOG_DEV', 'OTHER_SCIENCE_LATER']) {
  rejectMutation('D072 U10 cannot be assigned to ' + slice, (r) => {feature(r, 'FR-U10').suggested_release_slice = slice;}, /U10 cannot enter V1/);
}
rejectMutation('D072 rejects the complete pre-decision U10 timing rollback', (r) => {
  const hadith = feature(r, 'FR-U10');
  hadith.suggested_release_slice = 'V1_KNOWLEDGE'; hadith.classification = 'OWNER_APPROVAL_PENDING';
  hadith.development_scope = 'BLOCKED'; delete hadith.release_timing;
}, /D072/);
rejectMutation('D072 release timing cannot be silently omitted', (r) => {delete feature(r, 'FR-U10').release_timing;}, /all 28 U10 clauses/);
rejectMutation('D072 deferral cannot approve exact U10 clause contents', (r) => {
  const approval = feature(r, 'FR-U10').owner_approval;
  approval.status = 'OWNER_APPROVED'; approval.basis = 'REPOSITORY_DECISION_RECORD';
  approval.evidence_ids = ['TASK-D072']; approval.recorded_date = '2026-10-13';
}, /unit status changed/);
rejectMutation('D072 is deferral rather than U10 removal', (r) => {feature(r, 'FR-U10').owner_removal.status = 'REMOVED';}, /owner has not chosen/);
rejectMutation('D072 cannot exclude fewer than all 28 clauses', (r) => {feature(r, 'FR-U10').release_timing.applies_to = 'PARTIAL_U10';}, /fixed value/);
rejectMutation('D072 cannot undo first-release exclusion', (r) => {feature(r, 'FR-U10').release_timing.excluded_from_first_release = false;}, /fixed value/);
rejectMutation('D072 requires its exact dated owner timing decision', (r) => {feature(r, 'FR-U10').release_timing.recorded_date = '2026-10-14';}, /fixed value/);
rejectMutation('D072 evidence cannot be replaced by a clause-approval mandate', (r) => {feature(r, 'FR-U10').release_timing.evidence_ids = ['MANDATE-U03-U10', 'MANDATE-D068'];}, /all 28 U10 clauses/);
rejectMutation('D072 must remain linked to the U10 feature', (r) => {feature(r, 'FR-U10').evidence_ids = feature(r, 'FR-U10').evidence_ids.filter((id) => id !== 'TASK-D072');}, /all 28 U10 clauses/);
rejectMutation('D072 task provenance cannot use an invented source locator', (r) => {r.evidence.find((e) => e.id === 'TASK-D072').start_line = 1;}, /exact task provenance/);
rejectMutation('D072 cannot lend release-timing authority to another unit', (r) => {feature(r, 'FR-U03').release_timing = structuredClone(feature(r, 'FR-U10').release_timing);}, /applies only to U10/);
rejectMutation('D072 specialized Hadith source and rights blockers cannot be omitted', (r) => {feature(r, 'FR-U10').dependencies = feature(r, 'FR-U10').dependencies.filter((id) => !['HADITH_LIBRARY_SOURCE', 'SOURCE_RIGHTS'].includes(id));}, /source and rights blockers/);
rejectMutation('D072 specialist slice keeps gates and detailed acceptance dependencies', (r) => {r.slices.find((s) => s.id === 'HADITH_LIBRARY_POST_FIRST_RELEASE').dependency_ids = ['HADITH_LIBRARY_SOURCE'];}, /slice blocker omitted/);
rejectMutation('D072 specialist U10 deferral cannot govern broader science data', (r) => {r.slices.find((s) => s.id === 'OTHER_SCIENCE_LATER').dependency_ids.push('OWNER_U10');}, /distinct from broader science/);
rejectMutation('D068 planned V1 citation assistance cannot move after the first release', (r) => {feature(r, 'FR-D068-V1').suggested_release_slice = 'HADITH_LIBRARY_POST_FIRST_RELEASE';}, /missing or widened/);
rejectMutation('D068 citation assistance cannot depend on U10 approval or a specialist corpus', (r) => {feature(r, 'FR-D068-V1').dependencies.push('OWNER_U10', 'HADITH_LIBRARY_SOURCE');}, /independent of U10/);

rejectMutation('D072 broader science feature does not inherit specialist U10 approval', (r) => {feature(r, 'FR-D069-OTHER').dependencies.push('OWNER_U10');}, /distinct from broader science/);
rejectMutation('D068 planned V1 slice cannot acquire specialist U10 dependencies', (r) => {r.slices.find((s) => s.id === 'AI_V1_LATER').dependency_ids.push('OWNER_U10');}, /independent of U10/);

test('D072 tracked decision record verifies real bytes and rejects changed summary bytes', async () => {
  const bytes = new Map([['D072_RECORD', await readFile(new URL('../../../docs/product/D072_RELEASE_DEFERRAL.md', import.meta.url))]]);
  assert.deepEqual(verifySourceBytes(registry, bytes), []);
  bytes.set('D072_RECORD', Buffer.from('changed task-derived summary'));
  assert.match(verifySourceBytes(registry, bytes).join('\n'), /SHA256 mismatch/);
});

test('default CLI verifies tracked D072 while accurately reporting ignored task sources NOT_RUN', () => {
  const result = spawnSync(process.execPath, ['tools/feature_registry/validate.mjs'], {cwd: root, encoding: 'utf8'});
  assert.equal(result.status, 0);
  assert.match(result.stdout, /D072_RECORD PASS/);
  assert.match(result.stdout, /TASK_EVIDENCE NOT_RUN/);
  assert.match(result.stdout, /PINNED_ORIGINALS NOT_RUN/);
  assert.match(result.stdout, /live Decision Log NOT_VERIFIED/);
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
