import test from 'node:test';
import assert from 'node:assert/strict';
import { validateFixture,validateProfile,validateNode,ContractError } from '../../api_contract/catalog.ts';
import * as oracle from '../oracle.ts';
import { localOrigin } from '../transport.ts';
import { fixture,profile,base,reply,error,headers,escape } from './synthetic-target.ts';
const throws=(action:()=>unknown,code: string)=>assert.throws(action,error=>error instanceof ContractError&&error.code===code);
test('typed fixture and proposed profile validate without treating them as owner source data',()=>{
  validateFixture(fixture);validateProfile(profile);assert.equal(fixture.synthetic,true);assert.ok(fixture.source.edition.startsWith('SYNTHETIC'));
});
for(const [name,mutate,code] of [
  ['extra top-level field',(copy:any)=>copy.requester='private','SCHEMA_FIELDS'],
  ['nonsynthetic fixture',(copy:any)=>copy.synthetic=false,'FIXTURE_IDENTITY'],
  ['wrong fixture identity',(copy:any)=>copy.source.fixture_id='other','FIXTURE_IDENTITY'],
  ['duplicate identifier',(copy:any)=>copy.public_nodes[1].id=copy.public_nodes[0].id,'FIXTURE_IDS'],
  ['missing parent',(copy:any)=>copy.public_nodes[2].parent_id='unknown','FIXTURE_PARENT'],
  ['self cycle',(copy:any)=>copy.public_nodes[0].parent_id=copy.public_nodes[0].id,'FIXTURE_CYCLE'],
  ['incorrect children flag',(copy:any)=>copy.public_nodes[0].has_children=false,'FIXTURE_CHILDREN'],
  ['private marker in public title',(copy:any)=>copy.public_nodes[0].title=copy.private_canaries.markers[0],'FIXTURE_PRIVACY'],
  ['private marker sent as lookup',(copy:any)=>copy.private_canaries.lookup=copy.private_canaries.markers[0],'PRIVATE_CANARIES']
] as const) test('rejects invalid fixture: '+name,()=>{const copy=structuredClone(fixture);mutate(copy);throws(()=>validateFixture(copy),code);});
for(const [name,mutate,code] of [
  ['extra config field',(copy:any)=>copy.secret='unexpected','SCHEMA_FIELDS'],['external route',(copy:any)=>copy.routes.roots='https://example.invalid','PROFILE_ROUTE'],
  ['relative route',(copy:any)=>copy.routes.roots='api/roots/','PROFILE_ROUTE'],['traversal',(copy:any)=>copy.routes.roots='/../private/','PROFILE_ROUTE'],
  ['missing placeholder',(copy:any)=>copy.routes.node='/api/nodes/','PROFILE_ROUTE'],['unbounded page size',(copy:any)=>copy.max_page_size=1000000,'PROFILE_LIMITS'],
  ['relaxed forbidden status',(copy:any)=>copy.forbidden_statuses=[200],'PROFILE_STATUS'],['unbounded timeout',(copy:any)=>copy.timeout_ms=60000,'PROFILE_TRANSPORT'],
  ['duplicate params',(copy:any)=>copy.query_parameter=copy.page_parameter,'PROFILE_PARAMETER'],['forbidden/public overlap',(copy:any)=>copy.forbidden_paths[0]=copy.routes.roots,'PROFILE_FORBIDDEN']
] as const) test('rejects invalid profile: '+name,()=>{const copy=structuredClone(profile);mutate(copy);throws(()=>validateProfile(copy),code);});
test('node schema rejects private fields, altered edition and invalid citations',()=>{
  throws(()=>validateNode({...fixture.public_nodes[0],requester_id:'synthetic'},fixture.source),'SCHEMA_FIELDS');
  throws(()=>validateNode({...fixture.public_nodes[0],source:{...fixture.source,edition:'other'}},fixture.source),'SOURCE_ATTRIBUTION');
  throws(()=>validateNode({...fixture.public_nodes[0],printed_page:-1},fixture.source),'NODE_NUMBER');
});
test('JSON oracle rejects malformed content, wrong content type and noninteger counts',()=>{
  throws(()=>oracle.json(reply(200,'not JSON')),'JSON_PARSE');throws(()=>oracle.json(reply(200,'{}',{'content-type':'text/html'})),'JSON_CONTENT_TYPE');
  throws(()=>oracle.page(reply(200,{count:'2',next:null,previous:null,results:[]}),[],fixture,profile,localOrigin(base),profile.routes.search),'PUBLIC_COUNT');
});
test('pagination oracle rejects malicious, duplicate or inconsistent next links',()=>{
  const expected=fixture.public_nodes;const page={count:4,next:'/api/reference/search/?q=اختبار&page=2&page_size=2',previous:null,results:expected.slice(0,2)};
  oracle.page(reply(200,page),expected,fixture,profile,localOrigin(base),profile.routes.search,1,2,'اختبار');
  for(const next of ['https://example.invalid/','//example.invalid/','/api/reference/search/?q=اختبار&page=2&page_size=9999','/api/reference/search/?q=اختبار&page=2&page=3&page_size=2','/api/reference/search/?q=اختبار&page=2&page_size=2#hidden']) throws(()=>oracle.page(reply(200,{...page,next}),expected,fixture,profile,localOrigin(base),profile.routes.search,1,2,'اختبار'),'PAGE_LINK');
});
test('rejection oracle rejects debug traces, private error fields and redirects',()=>{
  throws(()=>oracle.errorResponse(reply(400,'Traceback (most recent call last)'),[400],fixture),'ERROR_DETAIL');
  throws(()=>oracle.errorResponse(reply(400,{error:{code:'R',message:'rejected',user_id:'synthetic'}}),[400],fixture),'SCHEMA_FIELDS');
  throws(()=>oracle.errorResponse(error(400,{location:'https://example.invalid'}),[400],fixture),'REDIRECT_REJECTED');
});
test('read-only oracle rejects CSRF masking and mutating Allow headers',()=>{
  throws(()=>oracle.readOnly(error(403),fixture),'HTTP_STATUS');throws(()=>oracle.readOnly(error(405,{allow:'GET, HEAD, POST'}),fixture),'ALLOW_METHODS');oracle.readOnly(error(405,{allow:'GET, HEAD'}),fixture);
});
test('private canaries are caught in JSON escapes, HTML entities, percent encodings and headers',()=>{
  const marker=fixture.private_canaries.markers[0];
  const encodings=[marker,marker.replace('S','\\u0053'),marker.replace('S','&#83;'),marker.replace('S','&#x53;'),marker.replace('S','%53')];
  for(const value of encodings) throws(()=>oracle.privacy(reply(400,{error:{code:'REJECTED',message:value}}),fixture),'PRIVATE_ARTIFACT');
  throws(()=>oracle.privacy(error(404,{'x-debug':marker}),fixture),'PRIVATE_ARTIFACT');
});
test('restrictive CSP cannot be weakened by script overrides or duplicate directives',()=>{
  for(const suffix of ["; script-src-elem *","; script-src-attr 'unsafe-inline'","; script-src *"]) throws(()=>oracle.securityHeaders(reply(200,'<html>',{'content-type':'text/html','content-security-policy':headers['content-security-policy']+suffix}),true),'HEADER_CSP');
});
test('HTML oracle accepts escaped fixture text and rejects executable XSS and missing form token',()=>{
  const payload="<img src=x onerror=alert('S4_XSS')>";const shell=(content:string)=>reply(200,'<html lang="ar" dir="rtl">'+content+'</html>',{'content-type':'text/html'});
  oracle.html(shell(escape(payload)),fixture,payload);
  throws(()=>oracle.html(shell(payload),fixture,payload),'XSS_EXECUTION');
  throws(()=>oracle.html(shell("<script>alert('S4_XSS')</script>"),fixture),'XSS_EXECUTION');
  throws(()=>oracle.html(shell('<form method="post"></form>'),fixture),'CSRF_FORM');
  throws(()=>oracle.html(shell('<form method="get"><button formmethod="post">Submit</button></form>'),fixture),'CSRF_FORM');
  oracle.html(shell('<form method="post"><input value = "'+'a'.repeat(64)+'" name = "csrfmiddlewaretoken"></form>'),fixture);
  oracle.html(shell('<form method="get"></form>'),fixture);
});
test('canonical snapshots ignore key order and catch public catalog drift',()=>{
  oracle.unchanged({a:1,b:2},{b:2,a:1});throws(()=>oracle.unchanged({count:4},{count:5}),'SIDE_EFFECT');
});
