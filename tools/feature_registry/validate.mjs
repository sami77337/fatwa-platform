import { createHash } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const UNIT_COUNTS = Object.freeze([31, 40, 48, 24, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28]);
export const SOURCE_PINS = Object.freeze({
  SPEC_TEXT: ['_codex_input/FATWA_PINNED_ORIGINAL_PRODUCT_SPEC_TEXT_20261010.txt', '5b810ace8c846fb1437165c36a2884f3b0134b3b3c51149290e125f95d28b8c7'],
  CLAUSE_INDEX: ['_codex_input/FATWA_PINNED_ORIGINAL_479_REQUIREMENTS_REGISTRY_20261010.jsonl', '48024cb9c1693d64c6e2c22928748f123c819ba37428016ca7cd8a26e2d175fb'],
  AGENTS: ['AGENTS.md', '04033feb603c07d9ea077bd64e21ea643a97b146e06c312991bd85fcaf2e2de7'],
  COORDINATION: ['docs/coordination/PARALLEL_EXECUTION_20261013.md', '58a21d2b685e7acafb82fb6286d7f6172db11d03bbc34a58f878402298c5e43f'],
  ISSUE_7: ['_codex_input/issue.md', '1487b1487165739a666bb22b38bea203c1d3e4225ab830d3bf2d7a097f492e84'],
});
const APPROVAL_LINES = Object.freeze({1: 135, 2: 301, 4: 616, 5: 758, 6: 904, 7: 1034, 8: 1173, 9: 1315, 11: 1595, 12: 1734, 13: 1870, 14: 2009, 15: 2148, 16: 2271});
const DEPENDENCY_STATES = Object.freeze({GATE_B: 'NOT_PASSED', GATE_C: 'HOLD', GATE_D: 'HOLD', GATE_E: 'HOLD', OWNER_U03: 'OWNER_APPROVAL_PENDING', OWNER_U10: 'OWNER_APPROVAL_PENDING', SOURCE_TOC: 'MISSING', SOURCE_RIGHTS: 'PENDING', PUBLIC_BASELINE: 'UNVERIFIED', OTHER_SCIENCE_SOURCE: 'MISSING', FULL_DECISION_LOG: 'MISSING', ORIGINAL_REVIEW: 'MISSING', OWNER_FEATURE_CHOICES: 'OWNER_APPROVAL_PENDING', OWNER_ACCEPTED_FUNCTIONS: 'OWNER_APPROVAL_PENDING'});
const SLICE_STATES = Object.freeze({PUBLIC_CATALOG_DEV: 'SAFE_DEV_ONLY', POLICY_DOCS: 'DOCUMENTATION_ONLY', SENSITIVE_WORKFLOWS: 'BLOCKED', V1_KNOWLEDGE: 'BLOCKED', AI_V1_LATER: 'DEFERRED', V2_EXTERNAL: 'DEFERRED', OTHER_SCIENCE_LATER: 'DEFERRED', DESIGN_LAST: 'DEFERRED', CURRENT_EXCLUSIONS: 'OUT_OF_SCOPE'});
const DECISION_FEATURES = Object.freeze({
  'FR-D067': ['OWNER_APPROVED', 'OWNER_APPROVED', 'POLICY_DOCS', 'DOCUMENTATION_ONLY', 'MANDATE-D067'],
  'FR-D068-V1': ['DEFERRED', 'OWNER_APPROVED', 'AI_V1_LATER', 'DEFERRED', 'MANDATE-D068'],
  'FR-D068-V2': ['DEFERRED', 'OWNER_APPROVED', 'V2_EXTERNAL', 'DEFERRED', 'MANDATE-D068'],
  'FR-D069': ['OWNER_APPROVED', 'OWNER_APPROVED', 'PUBLIC_CATALOG_DEV', 'READ_ONLY_DEV', 'MANDATE-D069'],
  'FR-D069-OTHER': ['DEFERRED', 'OWNER_APPROVED', 'OTHER_SCIENCE_LATER', 'DEFERRED', 'MANDATE-D069'],
  'FR-D070': ['DEFERRED', 'OWNER_APPROVED', 'DESIGN_LAST', 'DEFERRED', 'MANDATE-D070'],
  'FR-CURRENT-EXCLUSIONS': ['OUT_OF_SCOPE', 'UNKNOWN', 'CURRENT_EXCLUSIONS', 'PROHIBITED', 'MANDATE-PROHIBITIONS'],
  'FR-RELEASE-PROPOSAL': ['PROPOSED', 'UNKNOWN', 'POLICY_DOCS', 'DOCUMENTATION_ONLY', 'MANDATE-S6'],
});
const SHA = /^[a-f0-9]{64}$/;
export const sha256 = (value) => createHash('sha256').update(value).digest('hex');
export const sourceLines = (value) => value.toString('utf8').replace(/^\uFEFF/, '').split(/\r?\n/);
const unitCode = (unit) => 'U' + String(unit).padStart(2, '0');
const clauseId = (unit, number) => 'SPEC-' + unitCode(unit) + '-' + String(number).padStart(3, '0');

// Implements only the JSON Schema keywords used by our checked-in schema.
// Unsupported keywords fail closed; this is not a general JSON Schema library.
export function validateSchema(value, schema, root = schema, location = '$') {
  const errors = [];
  const allowed = new Set(['$schema', '$id', '$defs', 'title', 'description', '$ref', 'const', 'enum', 'type', 'required', 'properties', 'additionalProperties', 'items', 'minItems', 'uniqueItems', 'minLength', 'pattern', 'minimum', 'maximum']);
  for (const key of Object.keys(schema)) {
    if (!allowed.has(key)) errors.push(location + ': unsupported schema keyword');
  }
  if (schema.$ref) {
    const match = /^#\/\$defs\/([A-Za-z0-9_-]+)$/.exec(schema.$ref);
    if (!match || !Object.hasOwn(root.$defs ?? {}, match[1])) return [...errors, location + ': unresolved schema reference'];
    return [...errors, ...validateSchema(value, root.$defs[match[1]], root, location)];
  }
  if (Object.hasOwn(schema, 'const') && JSON.stringify(value) !== JSON.stringify(schema.const)) errors.push(location + ': fixed value changed');
  if (schema.enum && !schema.enum.includes(value)) errors.push(location + ': unsupported value');
  const type = value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
  const types = schema.type ? (Array.isArray(schema.type) ? schema.type : [schema.type]) : [];
  if (types.length && !types.some((t) => t === type || (t === 'integer' && Number.isInteger(value)))) {
    return [...errors, location + ': wrong type'];
  }
  if (type === 'object') {
    for (const key of schema.required ?? []) if (!Object.hasOwn(value, key)) errors.push(location + '.' + key + ': required');
    for (const [key, child] of Object.entries(value)) {
      if (Object.hasOwn(schema.properties ?? {}, key)) errors.push(...validateSchema(child, schema.properties[key], root, location + '.' + key));
      else if (schema.additionalProperties === false) errors.push(location + ': unexpected property');
    }
  } else if (type === 'array') {
    if (schema.minItems && value.length < schema.minItems) errors.push(location + ': too few items');
    if (schema.uniqueItems && new Set(value.map((v) => JSON.stringify(v))).size !== value.length) errors.push(location + ': duplicate items');
    if (schema.items) value.forEach((v, i) => errors.push(...validateSchema(v, schema.items, root, location + '[' + i + ']')));
  } else if (type === 'string') {
    if (schema.minLength && value.trim().length < schema.minLength) errors.push(location + ': blank value');
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) errors.push(location + ': invalid format');
  } else if (type === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(location + ': below minimum');
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(location + ': above maximum');
  }
  return errors;
}

function uniqueMap(items, name, errors) {
  const result = new Map();
  for (const item of items) {
    if (result.has(item.id)) errors.push(name + ': duplicate ID');
    result.set(item.id, item);
  }
  return result;
}
function checkRefs(refs, target, name, errors) {
  for (const id of refs) if (!target.has(id)) errors.push(name + ': dangling reference');
}

export function validateRegistry(registry, schema) {
  const errors = validateSchema(registry, schema);
  if (errors.length) return errors;
  const sources = uniqueMap(registry.sources, 'sources', errors);
  const evidence = uniqueMap(registry.evidence, 'evidence', errors);
  const dependencies = uniqueMap(registry.dependencies, 'dependencies', errors);
  const slices = uniqueMap(registry.slices, 'slices', errors);
  const features = uniqueMap(registry.features, 'features', errors);
  uniqueMap(registry.features.flatMap((f) => f.acceptance_criteria), 'acceptance criteria', errors);
  if (sources.size !== Object.keys(SOURCE_PINS).length) errors.push('sources: unexpected manifest size');
  for (const [id, [sourcePath, digest]] of Object.entries(SOURCE_PINS)) {
    const source = sources.get(id);
    const expectedKind = ['AGENTS', 'COORDINATION'].includes(id) ? 'REPOSITORY_MANDATE' : id === 'ISSUE_7' ? 'LOCAL_TASK_COPY' : 'LOCAL_PINNED_EXPORT';
    const expectedRevision = id === 'AGENTS' ? 'PARALLEL-RULES-20261013' : id === 'COORDINATION' ? 'PARALLEL-RUNBOOK-20261013' : id === 'ISSUE_7' ? 'ISSUE-7-LOCAL-20261013' : 'PINNED-20261010';
    if (!source || source.path !== sourcePath || source.sha256 !== digest || source.kind !== expectedKind || source.revision !== expectedRevision) errors.push('sources: pin mismatch');
  }
  for (const [id, state] of Object.entries(DEPENDENCY_STATES)) if (dependencies.get(id)?.status !== state) errors.push('dependencies: pinned blocker changed');
  for (const [id, state] of Object.entries(SLICE_STATES)) if (slices.get(id)?.status !== state) errors.push('slices: pinned release status changed');
  for (const slice of registry.slices) checkRefs(slice.dependency_ids, dependencies, 'slice dependencies', errors);
  for (const item of registry.evidence) {
    const source = sources.get(item.source_id);
    if (!source || item.revision !== source.revision) errors.push('evidence: unknown source or revision');
    if (item.end_line < item.start_line) errors.push('evidence: reversed line range');
    if ((item.kind === 'CLAUSE') !== Boolean(item.clause)) errors.push('evidence: clause metadata mismatch');
    if (item.kind === 'CLAUSE' && (item.source_id !== 'SPEC_TEXT' || item.decision_id !== 'SPEC-' + unitCode(item.clause.unit))) errors.push('evidence: wrong clause source/decision');
  }
  const clauses = registry.evidence.filter((e) => e.kind === 'CLAUSE');
  if (clauses.length !== 479) errors.push('coverage: expected 479 actual clause anchors');
  const indexLines = new Set(clauses.map((e) => e.clause.index_line));
  if (indexLines.size !== 479) errors.push('coverage: duplicate or missing source index line');
  const traced = new Set();
  for (let unit = 1; unit <= 16; unit += 1) {
    const uu = unitCode(unit);
    const group = features.get('FR-' + uu);
    const expected = UNIT_COUNTS[unit - 1];
    const unitClauses = clauses.filter((e) => e.clause.unit === unit);
    if (unitClauses.length !== expected || registry.coverage.unit_counts[uu] !== expected) errors.push('coverage: incorrect unit count');
    if (!group) { errors.push('features: missing unit group'); continue; }
    for (let number = 1; number <= expected; number += 1) {
      const id = clauseId(unit, number);
      const item = evidence.get(id);
      if (!item || item.clause?.number !== unit + '.' + number || !group.evidence_ids.includes(id)) errors.push('coverage: missing or misnumbered clause');
    }
    if (group.evidence_ids.some((id) => evidence.get(id)?.kind === 'CLAUSE' && evidence.get(id).clause.unit !== unit)) errors.push('coverage: clause assigned to wrong unit');
    const pending = unit === 3 || unit === 10;
    const requiredStatus = pending ? 'OWNER_APPROVAL_PENDING' : 'OWNER_APPROVED';
    if (group.classification !== requiredStatus || group.owner_approval.status !== requiredStatus) errors.push('approval: unit status changed without exact decision');
    if (group.development_scope !== 'BLOCKED') errors.push('scope: full product units remain blocked');
    for (const dep of ['GATE_B', 'GATE_C', 'GATE_D', 'GATE_E', ...(pending ? ['OWNER_' + uu] : [])]) if (!group.dependencies.includes(dep)) errors.push('dependencies: required unit blocker omitted');
    if (pending) {
      if (group.owner_approval.basis !== 'PENDING_MANDATE' || group.owner_approval.recorded_date !== null || JSON.stringify(group.owner_approval.evidence_ids) !== JSON.stringify(['MANDATE-U03-U10'])) errors.push('approval: pending unit cannot gain documentary acceptance');
    } else {
      const approval = evidence.get('APPROVAL-' + uu);
      if (!approval || approval.kind !== 'APPROVAL_MARKER' || approval.source_id !== 'SPEC_TEXT' || approval.start_line !== APPROVAL_LINES[unit] || approval.end_line !== APPROVAL_LINES[unit]) errors.push('approval: wrong exact unit approval anchor');
      if (group.owner_approval.basis !== 'DOCUMENTARY_UNIT_RECORD' || group.owner_approval.recorded_date !== '2026-10-07' || JSON.stringify(group.owner_approval.evidence_ids) !== JSON.stringify(['APPROVAL-' + uu])) errors.push('approval: unsupported unit approval basis');
    }
  }
  for (const [id, [classification, approval, slice, scope, anchor]] of Object.entries(DECISION_FEATURES)) {
    const feature = features.get(id);
    if (!feature || feature.classification !== classification || feature.owner_approval.status !== approval || feature.suggested_release_slice !== slice || feature.development_scope !== scope || !feature.evidence_ids.includes(anchor) || !feature.owner_approval.evidence_ids.includes(anchor)) errors.push('decisions: missing or widened D067/D068/D069/D070/current-scope record');
  }
  const catalog = features.get('FR-D069');
  for (const dep of ['SOURCE_TOC', 'SOURCE_RIGHTS', 'PUBLIC_BASELINE']) if (!catalog?.dependencies.includes(dep)) errors.push('catalog: required source or integration dependency omitted');
  for (const feature of registry.features) {
    checkRefs(feature.evidence_ids, evidence, 'feature evidence', errors);
    checkRefs(feature.owner_approval.evidence_ids, evidence, 'approval evidence', errors);
    checkRefs(feature.dependencies, dependencies, 'feature dependencies', errors);
    checkRefs(feature.implementation.evidence_ids, evidence, 'implementation evidence', errors);
    if (!slices.has(feature.suggested_release_slice)) errors.push('feature: unknown slice');
    for (const id of feature.evidence_ids) if (evidence.get(id)?.kind === 'CLAUSE') traced.add(id);
    if (feature.classification === 'OWNER_APPROVED' && feature.owner_approval.status !== 'OWNER_APPROVED') errors.push('approval: classification is not acceptance');
    if (feature.owner_approval.status === 'OWNER_APPROVED' && !['DOCUMENTARY_UNIT_RECORD', 'REPOSITORY_DECISION_RECORD'].includes(feature.owner_approval.basis)) errors.push('approval: unsupported evidence basis');
    if (feature.owner_approval.status === 'OWNER_APPROVED' && !/^FR-U(0[1-9]|1[0-6])$/.test(feature.id) && !Object.hasOwn(DECISION_FEATURES, feature.id)) errors.push('approval: no exact approved source record for new feature');
    if (feature.owner_approval.basis === 'REPOSITORY_DECISION_RECORD' && (!Object.hasOwn(DECISION_FEATURES, feature.id) || DECISION_FEATURES[feature.id][1] !== 'OWNER_APPROVED' || feature.owner_approval.recorded_date !== null)) errors.push('approval: repository decision has no exact owner acceptance date or broader scope');
    if (feature.classification === 'SUPERSEDED') errors.push('approval: no exact superseding decision is available in this revision');
    if (feature.classification === 'IMPLEMENTED_VERIFIED' || feature.implementation.status === 'IMPLEMENTED_VERIFIED' || feature.implementation.evidence_ids.length || feature.test_status !== 'NOT_RUN') errors.push('implementation: product verification evidence is absent in this revision');
    if (feature.owner_removal.status !== 'NOT_DECIDED' || feature.owner_removal.evidence_ids.length) errors.push('scope: owner has not chosen feature removals');
    if (feature.development_scope === 'READ_ONLY_DEV' && (feature.id !== 'FR-D069' || feature.security_sensitivity !== 'PUBLIC_METADATA')) errors.push('scope: only book 622 public metadata is a read-only development slice');
    for (const criterion of feature.acceptance_criteria) {
      checkRefs(criterion.source_evidence_ids, evidence, 'criterion evidence', errors);
      if (criterion.source_evidence_ids.some((id) => !feature.evidence_ids.includes(id))) errors.push('criterion: unrelated source clause');
      if (criterion.status !== 'NOT_RUN') errors.push('acceptance: planned checks are not executed product tests');
    }
  }
  if (traced.size !== 479 || registry.coverage.clauses_traced !== traced.size) errors.push('coverage: claimed trace differs from actual linked clauses');
  return errors;
}

export function verifySourceBytes(registry, bytesById) {
  const errors = [];
  for (const source of registry.sources) {
    const bytes = bytesById.get(source.id);
    if (bytes && sha256(bytes) !== source.sha256) errors.push('source bytes: SHA256 mismatch');
  }
  for (const item of registry.evidence) {
    const bytes = bytesById.get(item.source_id);
    if (!bytes) continue;
    const lines = sourceLines(bytes);
    if (item.start_line < 1 || item.end_line > lines.length || item.end_line < item.start_line || sha256(lines.slice(item.start_line - 1, item.end_line).join('\n')) !== item.text_sha256) errors.push('source evidence: exact line range/hash mismatch');
  }
  const indexBytes = bytesById.get('CLAUSE_INDEX');
  const specBytes = bytesById.get('SPEC_TEXT');
  if (Boolean(indexBytes) !== Boolean(specBytes)) errors.push('source bytes: both pinned originals are required together');
  if (indexBytes && specBytes) {
    let rows;
    try {
      const lines = sourceLines(indexBytes).filter((line) => line.trim());
      rows = lines.map((line) => JSON.parse(line));
    } catch { return [...errors, 'source index: invalid JSONL']; }
    if (rows.length !== 479 || new Set(rows.map((r) => r?.id)).size !== 479) errors.push('source index: expected 479 unique clauses');
    const spec = sourceLines(specBytes);
    const clauses = registry.evidence.filter((e) => e.kind === 'CLAUSE');
    for (const item of clauses) {
      const row = rows[item.clause.index_line - 1];
      if (!row || row.id !== item.id || row.unit !== item.clause.unit || row.number !== item.clause.number || row.start_line !== item.start_line || row.end_line !== item.end_line || row.text_sha256 !== item.text_sha256 || row.source_id !== 'S04' || row.source_path !== 'sources/04_product_spec.txt') {
        errors.push('source index: clause identity/locator mismatch'); continue;
      }
      if (typeof row.verbatim !== 'string' || !SHA.test(row.text_sha256) || sha256(row.verbatim) !== row.text_sha256 || spec.slice(row.start_line - 1, row.end_line).join('\n') !== row.verbatim) errors.push('source index: original clause bytes/lines mismatch');
    }
  }
  return errors;
}

// File reads stay within the explicit root. Export metadata never chooses a path.
export async function readContained(base, relative) {
  const baseReal = await realpath(base);
  const target = path.resolve(baseReal, relative);
  const targetReal = await realpath(target);
  const rel = path.relative(baseReal, targetReal);
  if (!rel || rel.startsWith('..' + path.sep) || rel === '..' || path.isAbsolute(rel)) throw new Error('Path outside input root');
  const info = await stat(targetReal);
  if (!info.isFile() || info.size > 4 * 1024 * 1024) throw new Error('Invalid or oversized input');
  return readFile(targetReal);
}

export async function main(args = process.argv.slice(2)) {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  let sourceDir;
  if (args.length) {
    if (args.length !== 2 || args[0] !== '--source-dir' || !args[1]) {
      console.error('Usage: node tools/feature_registry/validate.mjs [--source-dir PATH]'); return 2;
    }
    sourceDir = path.resolve(root, args[1]);
  }
  let registry, schema, bytesById;
  try {
    registry = JSON.parse((await readContained(root, 'docs/product/feature_registry.json')).toString('utf8'));
    schema = JSON.parse((await readContained(root, 'docs/product/feature_registry.schema.json')).toString('utf8'));
    const structural = validateRegistry(registry, schema);
    if (structural.length) {
      console.error('REGISTRY FAIL'); structural.slice(0, 64).forEach((e) => console.error(e)); return 1;
    }
    bytesById = new Map();
    for (const source of registry.sources) {
      if (source.kind === 'REPOSITORY_MANDATE') bytesById.set(source.id, await readContained(root, source.path));
      else if (sourceDir) bytesById.set(source.id, await readContained(sourceDir, path.basename(source.path)));
    }
    const errors = verifySourceBytes(registry, bytesById);
    if (errors.length) {
      console.error('SOURCE_EVIDENCE FAIL'); errors.slice(0, 64).forEach((e) => console.error(e)); return 1;
    }
  } catch {
    // Never echo raw source data, arbitrary parse errors or private filesystem paths.
    console.error('REGISTRY FAIL: required file unavailable, invalid JSON, oversized input or unsafe path'); return 1;
  }
  console.log('REGISTRY PASS: ' + registry.features.length + ' feature groups; 479 exact clause anchors; U03=48/U10=28 pending');
  console.log('REPOSITORY_EVIDENCE PASS: AGENTS and coordination SHA256/line anchors');
  console.log(sourceDir ? 'PINNED_ORIGINALS PASS: both source SHA256 pins, 479 identities, line ranges, clause hashes and approval anchors' : 'PINNED_ORIGINALS NOT_RUN: use --source-dir with the ignored local exports');
  console.log('PRODUCT_ACCEPTANCE NOT_RUN: ' + registry.features.reduce((n, f) => n + f.acceptance_criteria.length, 0) + ' planned group criteria; no integrated product or TOC fixture tested');
  console.log('NOT_DEPLOYED / GATES_HOLD: B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; all product activation DISABLED');
  return 0;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
