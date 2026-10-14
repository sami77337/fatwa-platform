// Artifact integrity checks only. These do not run the Python validator.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const schema = JSON.parse(readFileSync(new URL('../../contracts/inventory.schema.json', import.meta.url), 'utf8'));
const inventoryBytes = readFileSync(new URL('./fixtures/synthetic_inventory.json', import.meta.url));
const originalBytes = readFileSync(new URL('./fixtures/synthetic_review_excerpt.json', import.meta.url));
const inventory = JSON.parse(inventoryBytes);
const original = JSON.parse(originalBytes);

// Actual artifact pins, not owner-provided contract hashes.
const inventorySHA = '40df94e24af7d64b4fac4285000aa928282ac25f2110b07dce055d2994820dd4';
const originalSHA = '266e07ae6b229a19df2d11b8a9aa986e9cd468a05ecacfd7d22de3ebdd7b760d';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

test('schema and synthetic JSON artifacts parse with explicit identities', () => {
  assert.equal(schema.$schema, 'https://json-schema.org/draft/2020-12/schema');
  assert.equal(inventory.fixture_kind, 'SYNTHETIC');
  assert.equal(original.fixture_kind, 'SYNTHETIC');
});

test('every schema object requires its declared fields and rejects extensions', () => {
  const walk = rule => {
    if (rule.type === 'object') {
      assert.equal(rule.additionalProperties, false);
      assert.deepEqual([...rule.required].sort(), Object.keys(rule.properties).sort());
    }
    for (const child of Object.values(rule.properties ?? {})) walk(child);
    if (rule.items) walk(rule.items);
  };
  walk(schema);
});

test('fixture deliberately contains four actions and one transition', () => {
  assert.equal(inventory.actions.length, 4);
  assert.equal(inventory.transitions.length, 1);
  assert.equal(original.records.length, 5);
});

test('exact fixture hashes and original provenance references match', () => {
  assert.equal(hash(inventoryBytes), inventorySHA);
  assert.equal(hash(originalBytes), originalSHA);
  assert.equal(inventory.source_documents[0].sha256, originalSHA);
});

test('fixture rows have zero grant effects and no execution or history mutation', () => {
  for (const row of inventory.actions) {
    assert.equal(row.grant_effect, 'NONE');
    assert.equal(row.deny_default, 'DENY_DEFAULT');
    assert.equal(row.binding, 'NONE_CANDIDATE_BINDING_ONLY');
    assert.equal(row.callable, false);
    assert.equal(row.historical_answer_mutable, false);
  }
  for (const row of inventory.transitions) {
    assert.equal(row.enabled, false);
    assert.equal(row.grant_effect, 'NONE');
    assert.equal(row.historical_answer_mutable, false);
  }
});

test('known internal effect IDs have no candidate principals', () => {
  for (const id of ['P00-03::case.project', 'P00-03::delivery.hold']) {
    const row = inventory.actions.find(item => item.action_id === id);
    assert.equal(row.record_kind, 'INTERNAL_ATOMIC_EFFECT');
    assert.equal(row.parent_transaction, 'P00-03');
    assert.deepEqual(row.candidate_principals, []);
  }
});

test('synthetic record IDs match their small synthetic original excerpt', () => {
  const ids = new Set(original.records);
  assert.equal(new Set([...inventory.actions, ...inventory.transitions]
    .map(row => row.source_ref.record_id)).size, 5);
  for (const row of [...inventory.actions, ...inventory.transitions]) {
    assert.equal(row.source_ref.document_id, 'synthetic-review');
    assert.ok(ids.has(row.source_ref.record_id));
  }
});

test('fixture policy keeps pending gates, peer admins, and disabled AI', () => {
  assert.equal(inventory.policy.owner_approval, 'OWNER_APPROVAL_PENDING');
  assert.equal(inventory.policy.role_hierarchy.MUFTI, 'ADMIN_PEER');
  assert.equal(inventory.policy.role_hierarchy.ORGANIZER_ADMIN, 'ADMIN_PEER');
  assert.equal(inventory.policy.role_hierarchy.ORGANIZER, 'CONFIGURABLE_LOWER');
  assert.equal(inventory.policy.ai_mode, 'DISABLED');
  assert.equal(inventory.policy.gate_b, 'NOT_PASSED');
  assert.equal(inventory.policy.gates_c_d_e, 'HOLD');
  assert.equal(inventory.policy.phase01, 'BLOCKED');
});
