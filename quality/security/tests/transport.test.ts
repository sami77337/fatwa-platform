import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { createTransport,localOrigin,requestUrl } from '../transport.ts';
import { ContractError } from '../../api_contract/catalog.ts';
import { runSuite } from '../suite.ts';
import { fixture,profile,model } from './synthetic-target.ts';
async function serverFor(t: any,handler: Parameters<typeof http.createServer>[0]) {
  const server=http.createServer(handler);server.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(async()=>{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));});
  const address=server.address();assert.ok(address&&typeof address==='object');return 'http://127.0.0.1:'+address.port;
}
const code=(wanted:string)=>(error:unknown)=>error instanceof ContractError&&error.code===wanted;
test('only local origins without paths or credentials are accepted',()=>{
  for(const base of ['http://127.0.0.1:8000','http://localhost:8000','https://[::1]:8443']) localOrigin(base);
  for(const base of ['https://example.invalid','http://127.0.0.1.example.invalid','file:///tmp/data','http://user:pass@127.0.0.1','http://127.0.0.1/other','http://127.0.0.1/?secret=x','http://127.0.0.1/#fragment']) assert.throws(()=>localOrigin(base),code('LOCAL_TARGET'));
});
test('relative request paths cannot escape the loopback origin',()=>{
  const origin=localOrigin('http://127.0.0.1:8000');
  for(const path of ['//example.invalid/','https://example.invalid/','/\\example.invalid/','/path#fragment','/bad\nheader','/space path']) assert.throws(()=>requestUrl(origin,path),code('REQUEST_PATH'));
  assert.equal(requestUrl(origin,'/search/?q=%D8%B4').hostname,'127.0.0.1');
});
test('HTTP round trip preserves synthetic method/body and pins localhost to loopback',async t=>{
  let seen:any;const base=await serverFor(t,async(req,res)=>{let body='';for await(const chunk of req)body+=chunk;seen={method:req.method,body,host:req.headers.host};res.setHeader('content-type','application/json');res.end('{"ok":true}');});
  const url=new URL(base);const response=await createTransport('http://localhost:'+url.port,1000,4096)({method:'POST',path:'/probe/',body:'{"synthetic":true}'});
  assert.equal(response.status,200);assert.equal(response.body,'{"ok":true}');assert.equal(seen.method,'POST');assert.equal(seen.body,'{"synthetic":true}');assert.equal(seen.host,'localhost:'+url.port);
});
test('HTTP redirects are returned without being followed',async t=>{
  let calls=0;const base=await serverFor(t,(req,res)=>{calls++;res.writeHead(302,{location:'/destination/'});res.end();});
  const response=await createTransport(base,1000,4096)({method:'GET',path:'/'});assert.equal(response.status,302);assert.equal(response.headers.location,'/destination/');assert.equal(calls,1);
});
test('response streaming is limited by bytes',async t=>{
  const base=await serverFor(t,(_,res)=>res.end('x'.repeat(8192)));await assert.rejects(createTransport(base,1000,1024)({method:'GET',path:'/'}),code('RESPONSE_LIMIT'));
});
test('deadline also terminates a stalled streaming response',async t=>{
  const base=await serverFor(t,(_,res)=>{res.writeHead(200,{'content-type':'text/plain'});res.flushHeaders();res.write('one byte');});
  await assert.rejects(createTransport(base,100,1024)({method:'GET',path:'/'}),code('REQUEST_TIMEOUT'));
});
test('credentials and host overrides are refused before any request is made',async t=>{
  let calls=0;const base=await serverFor(t,(_,res)=>{calls++;res.end();});const transport=createTransport(base,1000,4096);
  for(const name of ['Authorization','Cookie','Host','Proxy-Authorization']) await assert.rejects(transport({method:'GET',path:'/',headers:{[name]:'S4_SYNTHETIC'}}),code('REQUEST_CREDENTIALS'));
  assert.equal(calls,0);
});
test('unsupported methods fail before issuing a request',async()=>{
  await assert.rejects(createTransport('http://127.0.0.1:1',1000,4096)({method:'TRACE',path:'/'}),code('REQUEST_METHOD'));
});
test('complete black-box HTTP suite passes against a disposable synthetic loopback server',async t=>{
  const target=model();const base=await serverFor(t,async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    const requestHeaders:Record<string,string>={};for(const [key,value]of Object.entries(req.headers)) if(typeof value==='string')requestHeaders[key]=value;
    const response=await target.transport({method:req.method,path:req.url,headers:requestHeaders,...(body?{body}:{})});
    res.writeHead(response.status,response.headers);res.end(response.body);
  });
  const result=await runSuite({fixture,profile,base,transport:createTransport(base,1000,profile.max_response_bytes),enableMutations:true,readLog:async()=>target.requests.map(req=>req.headers['x-s4-run-id']+' '+req.method).join('\n')});
  assert.equal(result.status,'PASS');assert.equal(result.log_check.status,'PASS');assert.ok(target.requests.length>100);
});
