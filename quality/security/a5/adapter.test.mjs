import test from 'node:test';
import assert from 'node:assert/strict';
import { createDjangoAdapter } from '../../../apps/reference/static/reference/django-api.mjs';
import { kind, pins } from './support.mjs';

// Synthetic responses only. Nothing in this file is sent to the site or a database.
const source = () => ({id:1,edition_key:'a5-synthetic-snapshot',title:'طبعة اصطناعية لاختبار A5',
  publisher:'ناشر اصطناعي',heading_count:2,root_count:1,max_depth:2,
  source_archive_sha256:pins.archive,source_input_sha256:pins.input,
  work:{source_namespace:'shamela',source_book_id:'622',title_original:'مرجع اختبار اصطناعي',madhhab:'حنبلي'}});
const row = (id=25,parent=null) => ({id,source_id:'622-'+id,parent_id:parent,
  title:'عنوان عربي <img src=x onerror=alert(622)> & "نص"',depth:parent===null?1:2,
  position:1,source_order:id,children_count:parent===null?1:0,part:'المقدمة',page:7,page_id:900+id,source_entry_number:null});
function transport(mutate = () => {}, options={}) {
  const calls=[];
  const fetchImpl=async (url, request) => {
    calls.push({url,request});
    const endpoint=new URL(url).pathname.split('/').at(-1);
    let payload;
    if (endpoint==='books') payload={kind,items:[source()],total:1,count:1,limit:100,offset:0,next_offset:null};
    else if (endpoint==='roots') payload={kind,edition:source(),items:[row()],total:1,count:1,limit:100,offset:0,next_offset:null};
    else if (endpoint==='children') payload={kind,edition:source(),parent:25,items:[row(26,25)],total:1,count:1,limit:20,offset:0,next_offset:null};
    else if (endpoint==='search') payload={kind,edition:source(),items:[row(26,25)],total:1,count:1,limit:20,offset:0,next_offset:null};
    else payload={kind,edition:source(),node:row(26,25),ancestors:[row(),row(26,25)]};
    mutate(payload,endpoint,request);
    return new Response(JSON.stringify(payload),{status:options.status??200,
      headers:{'content-type':options.contentType??'application/json'}});
  };
  return {calls,adapter:createDjangoAdapter({origin:'http://127.0.0.1:8000',fetchImpl,...options})};
}
const invalid = error => error?.code==='INVALID_PAYLOAD';

test('SYNTHETIC ADAPTER: requests are GET, no credentials, no redirects and encoded same origin',async()=>{
  const {adapter,calls}=transport(); await adapter.catalog(); await adapter.search("عنوان &x=' OR 1=1 --");
  for (const {url,request} of calls) {
    assert.equal(new URL(url).origin,'http://127.0.0.1:8000');
    assert.equal(request.method,'GET'); assert.equal(request.credentials,'omit');
    assert.equal(request.redirect,'error'); assert.equal(request.cache,'no-store');
    assert.deepEqual(request.headers,{Accept:'application/json'}); assert.ok(request.signal instanceof AbortSignal);
  }
  assert.equal(new URL(calls.at(-1).url).searchParams.get('q'),"عنوان &x=' OR 1=1 --");
  assert.equal(new URL(calls.at(-1).url).searchParams.has('x'),false);
});
test('SYNTHETIC ADAPTER: malicious Arabic source title remains exact text, unknown fields dropped',async()=>{
  const marker='A5_PRIVATE_CANARY_ONLY_IN_MEMORY';
  const {adapter}=transport((payload,endpoint)=>{for(const r of endpoint==='books'?[]:payload.items??[]) Object.assign(r,{fatwa_text:marker,
    requester:{email:marker},password:marker,user_id:marker,workflow:marker});});
  const catalog=await adapter.catalog(); const node=catalog.books[0];
  assert.equal(node.title,row().title); // No DOM execution is claimed by this assertion.
  assert.equal(node.source.source_id,'622-25');
  assert.ok(!JSON.stringify(catalog).includes(marker));
  assert.deepEqual(Object.keys(node).sort(),['id','parent_id','kind','title','depth','position','child_count','has_children','source'].sort());
});
test('SYNTHETIC ADAPTER: exact internal provenance survives without a public edition selector',async()=>{
  const {adapter}=transport(); const c=await adapter.catalog();
  assert.equal(c.source.edition_key,source().edition_key); assert.equal(c.source.source_archive_sha256,pins.archive);
  assert.equal(c.source.source_input_sha256,pins.input); assert.deepEqual(c.source.work,source().work);
  const child=await adapter.children('25');
  assert.equal(child.items[0].source.edition,source().title); assert.equal(child.items[0].source.page_id,926);
  assert.equal(child.items[0].source.printed_page,7); assert.equal(child.items[0].source.printed_part,'المقدمة');
});
test('SYNTHETIC ADAPTER: source hash/key/edition ID drift fails closed',async()=>{
  for(const key of ['source_archive_sha256','source_input_sha256','edition_key','id']) {
    const {adapter}=transport((p,endpoint)=>{if(endpoint==='roots') p.edition[key]=key==='id'?2:'c'.repeat(64);});
    await assert.rejects(adapter.catalog(),invalid,key);
  }
});
test('SYNTHETIC ADAPTER A5-001: non-hash edition/work metadata drift must fail closed',async()=>{
  const accepted=[];
  for(const key of ['title','publisher','heading_count','root_count','max_depth','work.source_book_id','work.source_namespace','work.title_original','work.madhhab']) {
    const {adapter}=transport((p,endpoint)=>{if(endpoint!=='roots')return;
      if(key.startsWith('work.')) p.edition.work[key.slice(5)]='A5_CHANGED_METADATA';
      else p.edition[key]=typeof p.edition[key]==='number'?19999:'A5_CHANGED_METADATA'; });
    try {await adapter.catalog(); accepted.push(key);} catch(error) {assert.ok(invalid(error),error.message);}
  }
  assert.deepEqual(accepted,[],'verifyEdition accepted changed source attribution with the same hashes/key');
});
test('SYNTHETIC ADAPTER: wrong content type, marker and HTTP errors are denied',async()=>{
  await assert.rejects(transport(()=>{},{contentType:'text/html'}).adapter.catalog(),invalid);
  await assert.rejects(transport(p=>{p.kind='FATWA_ANSWER';}).adapter.catalog(),invalid);
  for(const [status,code] of [[400,'INVALID_QUERY'],[404,'NOT_FOUND'],[503,'UNAVAILABLE']])
    await assert.rejects(transport(()=>{},{status}).adapter.catalog(),e=>e.code===code);
});
test('SYNTHETIC ADAPTER: unsafe IDs/cursors, mixed anchor paging and malformed input make no request',async()=>{
  const {adapter,calls}=transport(); await adapter.catalog(); const initial=calls.length;
  for(const id of ['../admin','25/../../admin','-1','0','9007199254740992','25?edition=2','٢٥'])
    await assert.rejects(adapter.node(id),invalid);
  for(const cursor of ['-1','20001','1e2','1&edition=2','01','../x'])
    await assert.rejects(adapter.children('25',{cursor}),invalid);
  await assert.rejects(adapter.children('25',{cursor:'1',anchorId:'26'}),invalid);
  for(const query of ['ا'.repeat(161),'كلمة '.repeat(11),'نص\u0000'])
    await assert.rejects(adapter.search(query),e=>e.code==='INVALID_QUERY');
  assert.equal(calls.length,initial);
});
test('SYNTHETIC ADAPTER: wrong child parent, malformed counts, leaf depth and oversized title rejected',async()=>{
  for(const mutation of [p=>{p.parent=69;},p=>{p.items[0].parent_id=69;},p=>{p.items[0].depth=6;},
    p=>{p.items[0].title='ا'.repeat(501);},p=>{p.total=20001;},p=>{p.limit=101;},
    p=>{p.next_offset=20;},p=>{p.items[0].depth=5;p.items[0].children_count=1;}]) {
    const {adapter}=transport((p,e)=>{if(e==='children')mutation(p);}); await adapter.catalog();
    await assert.rejects(adapter.children('25'),invalid);
  }
});
test('SYNTHETIC ADAPTER: invalid breadcrumb link and wrong requested node ID rejected',async()=>{
  for(const mutation of [p=>{p.node.id=27;},p=>{p.ancestors[1].parent_id=69;},p=>{p.ancestors=[];}]) {
    const {adapter}=transport((p,e)=>{if(!['books','roots'].includes(e))mutation(p);}); await adapter.catalog();
    await assert.rejects(adapter.node('26'),invalid);
  }
});
test('SYNTHETIC ADAPTER A5-002: root list must reject a non-root heading',async()=>{
  const {adapter}=transport((p,e)=>{if(e==='roots'){p.items=[row(26,25)];}});
  await assert.rejects(adapter.catalog(),invalid,'Catalog accepted a depth-two heading as its sole root');
});
test('SYNTHETIC ADAPTER A5-002: breadcrumb depth must agree with the parent path',async()=>{
  const {adapter}=transport((p,e)=>{if(!['books','roots'].includes(e)){p.node.depth=5;p.ancestors[1].depth=5;}});
  await adapter.catalog();
  await assert.rejects(adapter.node('26'),invalid,'Depth-five leaf accepted with only a depth-one parent');
});
test('SYNTHETIC ADAPTER: network failure never falls back to synthetic catalog data',async()=>{
  const adapter=createDjangoAdapter({origin:'http://127.0.0.1:8000',fetchImpl:async()=>{throw Error('A5_TEST_NETWORK_FAILURE');}});
  await assert.rejects(adapter.catalog(),/A5_TEST_NETWORK_FAILURE/);
});
test('SYNTHETIC ADAPTER: timeout and caller abort are distinguished without retry/write',async()=>{
  const pending=async(url,{signal})=>new Promise((resolve,reject)=>{
    if(signal.aborted)reject(new DOMException('Aborted','AbortError'));
    else signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});
  });
  const timeout=createDjangoAdapter({origin:'http://127.0.0.1:8000',fetchImpl:pending,timeoutMs:5});
  await assert.rejects(timeout.catalog(),e=>e.code==='TIMEOUT');
  const controller=new AbortController(); controller.abort();
  await assert.rejects(createDjangoAdapter({origin:'http://127.0.0.1:8000',fetchImpl:pending}).catalog({signal:controller.signal}),e=>e.name==='AbortError');
});
