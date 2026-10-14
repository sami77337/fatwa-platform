import { ContractError, check, validateFixture, validateProfile, ordered } from '../api_contract/catalog.ts';
import type { Fixture, Profile, CatalogNode } from '../api_contract/catalog.ts';
import type { Request, Response, Transport } from './transport.ts';
import { localOrigin } from './transport.ts';
import * as oracle from './oracle.ts';
export type CaseResult = { id: string; status: 'PASS'|'FAIL'|'NOT_RUN'|'SERVER_NOT_AVAILABLE'; requests: number; http_statuses: number[]; code?: string };
export type SuiteResult = { status: 'PASS'|'FAIL'|'INCOMPLETE'|'SERVER_NOT_AVAILABLE'; cases: CaseResult[]; scope: 'SYNTHETIC_DEVELOPMENT_ONLY'; log_check: CaseResult; limitations: string[] };
type Case = { id: string; run: () => Promise<void> };
export function queryPath(profile: Profile, route: string, params: Record<string,string>): string {
  return route+'?'+new URLSearchParams(params).toString();
}
export async function runSuite(input: { fixture: Fixture; profile: Profile; base: string; transport: Transport; enableMutations: boolean; logText?: string; readLog?: () => Promise<string>; runMarker?: string }): Promise<SuiteResult> {
  const {fixture,profile,transport}=input; validateFixture(fixture); validateProfile(profile); const origin=localOrigin(input.base);
  const results: CaseResult[]=[]; let calls: number[]=[]; let attempts=0; const runMarker=input.runMarker ?? 'S4_SYNTHETIC_UNIT_RUN';
  const request=async (req: Request) => { attempts++; const response=await transport({...req,headers:{...req.headers,'x-s4-run-id':runMarker}}); calls.push(response.status); return response; };
  const params=(q?: string,p=1,size=profile.max_page_size) => ({[profile.page_parameter]:String(p),[profile.page_size_parameter]:String(size),...(q===undefined?{}:{[profile.query_parameter]:q})});
  const collection=async (route: string,nodes: CatalogNode[],q?: string,p=1,size=profile.max_page_size) => {
    const response=await request({method:'GET',path:queryPath(profile,route,params(q,p,size))});
    return oracle.page(response,nodes,fixture,profile,origin,route,p,size,q);
  };
  const publicQuery='اختبار';
  check(fixture.public_nodes.every(node=>node.title.includes(publicQuery)), 'FIXTURE_QUERY','Every synthetic public node must match the fixed positive selector.');
  const snapshot=async () => {
    const pages=[];
    for(let p=1;p<=Math.ceil(fixture.public_nodes.length/profile.max_page_size);p++) pages.push(await collection(profile.routes.search,fixture.public_nodes,publicQuery,p));
    return pages;
  };
  const resultFor=(id: string,status: CaseResult['status'],code?: string): CaseResult => ({id,status,requests:attempts,http_statuses:[...calls],...(code?{code}:{})});
  const safeCode=(error: unknown) => error instanceof ContractError ? error.code : 'HARNESS_ERROR';
  let baseline: unknown;
  try { baseline=await snapshot(); results.push(resultFor('public-fixture-preflight','PASS')); }
  catch(error) {
    const code=safeCode(error); const unavailable=['SERVER_NOT_AVAILABLE','REQUEST_TIMEOUT'].includes(code);
    results.push(resultFor('public-fixture-preflight',unavailable?'SERVER_NOT_AVAILABLE':'FAIL',code));
    return {status:unavailable?'SERVER_NOT_AVAILABLE':'FAIL',cases:results,scope:'SYNTHETIC_DEVELOPMENT_ONLY',log_check:{id:'private-artifacts-in-local-log',status:'NOT_RUN',requests:0,http_statuses:[],code:'PREFLIGHT_FAILED'},limitations:['Remaining probes were NOT_RUN because the local fixture preflight did not pass.','No source ZIP, PostgreSQL, authenticated session, cache internals or production acceptance was verified.']};
  }
  calls=[]; attempts=0;
  const cases: Case[]=[]; const add=(id: string,run: Case['run'])=>cases.push({id,run});
  const roots=fixture.public_nodes.filter(node=>node.parent_id===null);
  for(let p=1;p<=roots.length;p++) add('public-roots-page-'+p,async()=>{await collection(profile.routes.roots,roots,undefined,p,1);});
  for(const expected of fixture.public_nodes) {
    add('public-node-'+expected.id,async()=>oracle.node(await request({method:'GET',path:profile.routes.node.replace('{id}',expected.id)}),expected,fixture));
    add('public-children-'+expected.id,async()=>{await collection(profile.routes.children.replace('{id}',expected.id),fixture.public_nodes.filter(node=>node.parent_id===expected.id));});
  }
  add('public-search-positive',async()=>{const q='فرع';await collection(profile.routes.search,fixture.public_nodes.filter(node=>node.title.includes(q)),q);});
  add('public-search-idempotent',async()=>oracle.unchanged(baseline,await snapshot()));
  const publicRoutes=[profile.routes.roots,profile.routes.node.replace('{id}',roots[0].id),profile.routes.children.replace('{id}',roots[0].id),queryPath(profile,profile.routes.search,params(publicQuery))];
  for(let i=0;i<publicRoutes.length;i++) add('public-head-'+i,async()=>{
    const response=await request({method:'HEAD',path:publicRoutes[i]});
    check(response.status===200 && response.body==='','HEAD_RESPONSE','HEAD must succeed without a body.'); oracle.privacy(response,fixture); oracle.securityHeaders(response);
  });
  add('public-web-positive',async()=>{
    const response=await request({method:'GET',path:profile.routes.web}); oracle.html(response,fixture);
    check(response.body.includes(fixture.source.work_title) && response.body.includes(fixture.source.edition) && response.body.includes('حنبلي') && response.body.includes('مرجع'),'WEB_ATTRIBUTION','Web catalog lacks source edition and Hanbali reference labels.');
  });
  const xss="<img src=x onerror=alert('S4_XSS')>";
  add('xss-literal-json',async()=>{await collection(profile.routes.search,fixture.public_nodes.filter(node=>node.title.includes(xss)),xss);});
  add('xss-escaped-web-title',async()=>{
    const response=await request({method:'GET',path:queryPath(profile,profile.routes.web_search,params('فرع'))}); oracle.html(response,fixture,xss);
    check(response.body.includes('&lt;img') && response.body.includes('S4_XSS'),'XSS_FIXTURE_VISIBLE','Escaped seeded title must be visible on the positive web search.');
  });
  add('xss-escaped-web-query',async()=>oracle.html(await request({method:'GET',path:queryPath(profile,profile.routes.web_search,params(xss))}),fixture,xss));
  for(const [index,q] of ["' OR 1=1 --", "'; DROP TABLE reference_node; --", '" UNION SELECT NULL --'].entries()) add('sql-literal-'+index,async()=>{await collection(profile.routes.search,[],q);oracle.unchanged(baseline,await snapshot());});
  const invalid: Array<[string,string,string]>=[
    ['oversized-page',profile.page_size_parameter,String(profile.max_page_size+1)],['huge-page',profile.page_size_parameter,'1000000'],
    ['zero-page-size',profile.page_size_parameter,'0'],['negative-page-size',profile.page_size_parameter,'-1'],['noninteger-page-size',profile.page_size_parameter,'1.5'],
    ['zero-page',profile.page_parameter,'0'],['negative-page',profile.page_parameter,'-1'],['noninteger-page',profile.page_parameter,'abc'],
    ['long-query',profile.query_parameter,'ش'.repeat(profile.max_query_length+1)],['empty-query',profile.query_parameter,''],['blank-query',profile.query_parameter,'   ']
  ];
  for(const [id,key,value] of invalid) add('bounds-'+id,async()=>{
    const response=await request({method:'GET',path:queryPath(profile,profile.routes.search,{...params(publicQuery),[key]:value})}); oracle.errorResponse(response,[profile.validation_status],fixture);
  });
  add('bounds-query-at-limit',async()=>{await collection(profile.routes.search,[],'ش'.repeat(profile.max_query_length));});
  for(const key of [profile.query_parameter,profile.page_parameter,profile.page_size_parameter]) add('bounds-duplicate-'+key,async()=>{
    const path=queryPath(profile,profile.routes.search,params(publicQuery))+'&'+key+'='+encodeURIComponent(key===profile.query_parameter?publicQuery:'1');
    oracle.errorResponse(await request({method:'GET',path}),[profile.validation_status],fixture);
  });
  add('bounds-missing-page',async()=>oracle.errorResponse(await request({method:'GET',path:queryPath(profile,profile.routes.search,params(publicQuery,999999))}),[profile.validation_status,profile.missing_status],fixture));
  for(const [index,destination] of ['https://example.invalid/','//example.invalid/','javascript:alert(1)','/\\example.invalid/'].entries()) add('unsafe-redirect-'+index,async()=>{
    const path=queryPath(profile,profile.routes.web_search,{...params(publicQuery),next:destination});
    oracle.errorResponse(await request({method:'GET',path}),[profile.validation_status],fixture);
  });
  add('private-search-and-repeat',async()=>{
    const first=await collection(profile.routes.search,[],fixture.private_canaries.lookup); const second=await collection(profile.routes.search,[],fixture.private_canaries.lookup); oracle.unchanged(first,second);
  });
  add('private-node-not-public',async()=>oracle.errorResponse(await request({method:'GET',path:profile.routes.node.replace('{id}',fixture.private_canaries.hidden_node_id)}),[profile.missing_status],fixture));
  for(const [index,path] of profile.forbidden_paths.entries()) add('forbidden-get-'+index,async()=>oracle.errorResponse(await request({method:'GET',path}),profile.forbidden_statuses,fixture));
  const mutationBody=JSON.stringify({probe:'S4_SYNTHETIC_ONLY',action:'forbidden',title:'S4 synthetic mutation must be rejected'});
  const mutationIds = new Set<string>();
  const mutation=(id: string,path: string,method: string,publicRoute: boolean,headers?: Record<string,string>)=>{
    mutationIds.add(id); add(id,async()=>{
      const before=await snapshot(); const response=await request({method,path,body:mutationBody,headers});
      // Observe state even when a rejection's status/body is wrong.
      const after=await snapshot(); oracle.unchanged(before,after); oracle.unchanged(baseline,after);
      if(publicRoute) oracle.readOnly(response,fixture); else oracle.errorResponse(response,profile.forbidden_statuses,fixture);
    });
  };
  for(const method of ['POST','PUT','PATCH','DELETE']) {
    for(const [index,path] of [...publicRoutes,profile.routes.web,profile.routes.web_search].entries()) mutation('readonly-'+method+'-'+index,path,method,true);
    for(const [index,path] of profile.forbidden_paths.entries()) mutation('forbidden-'+method+'-'+index,path,method,false);
  }
  for(const role of ['MUFTI','ORGANIZER_ADMIN','ORGANIZER','DOMAIN_TRANSACTION']) mutation('forged-role-'+role,profile.forbidden_paths[0],'POST',false,{'x-role':role});
  mutation('csrf-invalid-web-token',profile.routes.web_search,'POST',true,{'x-csrftoken':'S4INVALIDSYNTHETICTOKEN'});
  add('final-public-state-unchanged',async()=>oracle.unchanged(baseline,await snapshot()));
  let transportAborted=false;
  for(const entry of cases) {
    calls=[]; attempts=0;
    if(transportAborted) { results.push(resultFor(entry.id,'NOT_RUN','TRANSPORT_ABORTED')); continue; }
    if(mutationIds.has(entry.id) && !input.enableMutations) { results.push(resultFor(entry.id,'NOT_RUN','DISPOSABLE_TARGET_REQUIRED')); continue; }
    try { await entry.run(); results.push(resultFor(entry.id,'PASS')); }
    catch(error) {
      const code=safeCode(error);results.push(resultFor(entry.id,'FAIL',code));
      if(['SERVER_NOT_AVAILABLE','REQUEST_TIMEOUT','RESPONSE_ERROR','RESPONSE_ABORTED'].includes(code)) transportAborted=true;
    }
  }
  let logCheck: CaseResult={id:'private-artifacts-in-local-log',status:'NOT_RUN',requests:0,http_statuses:[],code:'LOCAL_LOG_NOT_SUPPLIED'};
  if(input.logText!==undefined || input.readLog!==undefined) {
    try {
      const logText=input.readLog ? await input.readLog() : input.logText;
      check(logText.length>0 && Buffer.byteLength(logText)<=1048576,'LOG_EVIDENCE','Expected a bounded nonempty test-only log.');
      check(logText.includes(runMarker),'LOG_CORRELATION','Test log must include the current synthetic run marker.');
      oracle.privateText(logText,fixture,'PRIVATE_LOG_ARTIFACT');
      logCheck={...logCheck,status:'PASS',code:undefined};
    } catch(error) { logCheck={...logCheck,status:'FAIL',code:safeCode(error)}; }
  }
  const failed=results.some(entry=>entry.status==='FAIL') || logCheck.status==='FAIL';
  const incomplete=results.some(entry=>entry.status==='NOT_RUN') || logCheck.status==='NOT_RUN';
  return {status:failed?'FAIL':incomplete?'INCOMPLETE':'PASS',cases:results,scope:'SYNTHETIC_DEVELOPMENT_ONLY',log_check:logCheck,limitations:[
    'Only the identified synthetic public fixture and private canaries are covered; original source ZIP acceptance is NOT_RUN.',
    'Black-box snapshots cover observable public state. Private database writes, shared-cache internals and middleware installation are NOT independently observable.',
    'Authenticated CSRF/session/RBAC and future business interfaces remain deferred. No credentials or private production data were used.',
    'No PostgreSQL version, migration, production deployment or owner policy gate was validated.'
  ]};
}
