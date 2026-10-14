import test from 'node:test';
import assert from 'node:assert/strict';
import { ContractError } from '../../api_contract/catalog.ts';
import { runSuite } from '../suite.ts';
import { fixture,profile,base,model } from './synthetic-target.ts';
const goodLog='S4_SYNTHETIC_UNIT_RUN GET /reference/ synthetic local test';
async function execute(mode='safe',extra: Record<string,unknown>={}) {
  const target=model(mode); const result=await runSuite({fixture,profile,base,transport:target.transport,enableMutations:true,logText:goodLog,...extra}); return {target,result};
}
test('safe synthetic model passes positive and negative probes with public state snapshots',async()=>{
  const {target,result}=await execute(); assert.equal(result.status,'PASS'); assert.ok(result.cases.length>=100); assert.equal(result.log_check.status,'PASS');
  assert.ok(result.cases.every(entry=>entry.status==='PASS')); assert.ok(result.cases.some(entry=>entry.id==='public-web-positive'));
  assert.ok(result.cases.some(entry=>entry.id==='xss-escaped-web-title')); assert.ok(result.cases.some(entry=>entry.id==='public-search-positive'));
  for(const method of ['POST','PUT','PATCH','DELETE']) assert.ok(target.requests.some(req=>req.method===method));
  assert.ok(target.requests.every(req=>!req.headers?.authorization&&!req.headers?.cookie));
  assert.ok(target.requests.every(req=>req.headers?.['x-s4-run-id']==='S4_SYNTHETIC_UNIT_RUN'));
  assert.ok(result.cases.filter(entry=>entry.id.startsWith('readonly-')).every(entry=>entry.requests>=5));
});
for(const [mode,code] of [
  ['deny-all','HTTP_STATUS'],['private-field','SCHEMA_FIELDS'],['private-header','PRIVATE_ARTIFACT'],['wrong-source','SOURCE_ATTRIBUTION'],
  ['oversized-page','PAGE_BOUND'],['cross-origin-page','PAGE_LINK'],['no-security-headers','HEADER_NOSNIFF'],
  ['sql-injection','PUBLIC_COUNT'],['reflects-xss','XSS_EXECUTION'],['missing-csrf','CSRF_FORM'],['open-redirect','HTTP_STATUS'],
  ['allows-write','HTTP_STATUS'],['csrf-masks-route','HTTP_STATUS'],['mutates-on-denial','PAGE_CONTENT'],['cache-leak','PRIVATE_ARTIFACT']
]) test('rejects deliberately unsafe synthetic target: '+mode,async()=>{
  const {result}=await execute(mode); assert.equal(result.status,'FAIL'); assert.ok(result.cases.some(entry=>entry.code===code),JSON.stringify(result.cases.filter(entry=>entry.status==='FAIL')));
});
test('unavailable backend is reported accurately and no remaining requests are made',async()=>{
  let attempts=0; const result=await runSuite({fixture,profile,base,enableMutations:false,transport:async()=>{attempts++;throw new ContractError('SERVER_NOT_AVAILABLE','secret backend detail');}});
  assert.equal(result.status,'SERVER_NOT_AVAILABLE'); assert.equal(attempts,1); assert.equal(result.cases[0].requests,1); assert.equal(result.log_check.status,'NOT_RUN');
  assert.ok(!JSON.stringify(result).includes('secret backend detail'));
});
test('missing log evidence keeps runtime incomplete',async()=>{
  const {result}=await execute('safe',{logText:undefined}); assert.equal(result.status,'INCOMPLETE'); assert.equal(result.log_check.code,'LOCAL_LOG_NOT_SUPPLIED');
});
test('mutation acknowledgement is required, while positive read tests still run',async()=>{
  const {target,result}=await execute('safe',{enableMutations:false}); assert.equal(result.status,'INCOMPLETE');
  assert.ok(result.cases.some(entry=>entry.status==='NOT_RUN')); assert.ok(target.requests.every(req=>['GET','HEAD'].includes(req.method)));
});
test('private markers in test-only logs fail without disclosing them in results',async()=>{
  const {result}=await execute('safe',{logText:goodLog+' '+fixture.private_canaries.markers[0]}); assert.equal(result.status,'FAIL'); assert.equal(result.log_check.code,'PRIVATE_LOG_ARTIFACT');
  assert.ok(!JSON.stringify(result).includes(fixture.private_canaries.markers[0]));
});
test('unrelated log cannot produce a pass',async()=>{
  const {result}=await execute('safe',{logText:'an unrelated old log'}); assert.equal(result.log_check.status,'FAIL'); assert.equal(result.log_check.code,'LOG_CORRELATION');
});
test('log adapter reads after the request matrix completes',async()=>{
  const target=model(); let countAtRead=0;
  const result=await runSuite({fixture,profile,base,transport:target.transport,enableMutations:true,readLog:async()=>{countAtRead=target.requests.length;return goodLog;}});
  assert.equal(result.status,'PASS'); assert.equal(countAtRead,target.requests.length); assert.ok(countAtRead>100);
});
test('unexpected transport exceptions are sanitized',async()=>{
  const result=await runSuite({fixture,profile,base,enableMutations:false,transport:async()=>{throw new Error('sensitive response');}});
  assert.equal(result.status,'FAIL'); assert.equal(result.cases[0].code,'HARNESS_ERROR'); assert.ok(!JSON.stringify(result).includes('sensitive response'));
});

test('read-only-only run still detects changes made by a forbidden GET',async()=>{
  const {result}=await execute('mutates-on-forbidden-get',{enableMutations:false});assert.equal(result.status,'FAIL');
  assert.equal(result.cases.find(entry=>entry.id==='final-public-state-unchanged').code,'PAGE_CONTENT');
});
test('transport loss during the matrix marks remaining cases NOT_RUN',async()=>{
  const target=model();let attempts=0;
  const result=await runSuite({fixture,profile,base,enableMutations:true,logText:goodLog,transport:async req=>{
    attempts++;if(attempts===3)throw new ContractError('SERVER_NOT_AVAILABLE','connection detail');return target.transport(req);
  }});
  assert.equal(result.status,'FAIL');assert.equal(attempts,3);assert.ok(result.cases.some(entry=>entry.code==='TRANSPORT_ABORTED'&&entry.status==='NOT_RUN'));
});
