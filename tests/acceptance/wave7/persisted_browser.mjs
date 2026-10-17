// Mandatory actual persisted browser journeys. Services/commands never write over HTTP.
import assert from "node:assert/strict";
import {spawn,execFile,execFileSync} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,readFile,writeFile,rm} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import path from "node:path";
import os from "node:os";
import {CDP,loopbackOrigin,permittedRequest} from "./cdp.mjs";
import {dispatchKey} from "./keyboard.mjs";

const root=fileURLToPath(new URL("../../../",import.meta.url));
const origin=loopbackOrigin(process.argv[2]);
const scenario=JSON.parse(await readFile(process.argv[3],"utf8")); // generated metadata/source strings only
const route="/dev/editorial-preview/persisted";
assert.equal(scenario.worklist_path,route);
assert.equal(scenario.batch_ids.length,2);
for(const target of [...scenario.detail_paths,scenario.blocked_detail_path,scenario.reviewed_detail_path,
  scenario.missing_media_detail_path,scenario.invalid_media_detail_path,scenario.unresolved_detail_path]){
  assert.equal(new URL(target,origin).origin,origin);assert.equal(new URL(target,origin).pathname,route);
}
const executable=process.env.E6_BROWSER??"/usr/bin/chromium";
assert.ok(process.env.E6_PYTHON,"Python executable must be supplied by the guarded Django test");
const artifacts=path.resolve(process.env.E6_WAVE7_ARTIFACTS??"/tmp/e6-wave7-browser");
await mkdir(artifacts,{recursive:true});
const git=(...args)=>execFileSync("git",args,{cwd:root,encoding:"utf8"}).trim();
const report={schema:"fatwa.e6.wave7.persisted-browser.v1",sha:git("rev-parse","HEAD"),
  dirty_paths:git("status","--porcelain").split("\n").filter(Boolean),
  scope:"Actual persisted synthetic E1/E2/E3 services and PR61 GET UI",result:"NOT_RUN",tests:[],
  source_acceptance:"NOT_RUN",screenshots:[],service_processes:[],http_preflight:[],asset_preflight:[],
  environment:{node:process.version,platform:os.platform(),release:os.release()},
  command:["node","tests/acceptance/wave7/persisted_browser.mjs",origin,"<generated-scenario>"],
  console_errors:[],exceptions:[],requests:[],unwanted_requests:[]};
try{report.environment.browser=execFileSync(executable,["--version"],{encoding:"utf8"}).trim();}
catch{report.environment.browser="unavailable";}
let browser,socket,cdp,stderr="",phase="service-preflight",loads=0;
const profile=await mkdtemp(path.join(os.tmpdir(),"fatwa-wave7-e6-persisted-"));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label){const end=Date.now()+12000;while(Date.now()<end){if(await check())return;await pause(40);}throw Error("Timed out: "+label);}
const evaluate=expression=>cdp.evaluate(expression);
const wait=expression=>until(()=>evaluate(expression),expression);
const body=()=>evaluate("document.body.innerText");
async function navigate(target){const before=loads;await cdp.send("Page.navigate",{url:origin+target});await until(()=>loads>before,"document load");await wait("document.readyState==='complete'");}
async function reload(){const before=loads;await cdp.send("Page.reload");await until(()=>loads>before,"reload");await wait("document.readyState==='complete'");}
async function submit(){const before=loads;await dispatchKey(cdp,"Enter",13);await until(()=>loads>before,"native Enter submit");await wait("document.readyState==='complete'");}
async function click(selector){const before=loads;await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);await until(()=>loads>before,"link navigation");await wait("document.readyState==='complete'");}
async function backForward(direction){const previous=await evaluate("location.href");await evaluate(`history.${direction}()`);await wait(`location.href!==${JSON.stringify(previous)} && document.readyState==='complete'`);}
async function returnToList(){const before=loads;await evaluate("[...document.querySelectorAll('#wave7-persisted a')].find(a=>a.textContent.includes('العودة إلى القائمة المصفاة')).click()");await until(()=>loads>before,"return link");}
async function screenshot(name){const result=await cdp.send("Page.captureScreenshot",{format:"png",captureBeyondViewport:true});await writeFile(path.join(artifacts,name),Buffer.from(result.data,"base64"));report.screenshots.push(name);}
async function child(action,options){
  const args=[path.join(root,"tests/acceptance/wave7/workflow_process.py"),action,...options];
  let stdout,exit=0;
  try{({stdout}=await promisify(execFile)(process.env.E6_PYTHON,args,{cwd:root,timeout:45000,maxBuffer:1000000,env:process.env}));}
  catch(error){if(error.code!==3)throw error;stdout=error.stdout;exit=3;}
  const result=JSON.parse(stdout);report.service_processes.push({action,exit});return {result,exit};
}
const query=(batch,extra={})=>route+"?"+new URLSearchParams({batch,...extra});
const cases=[
  ["desktop batch selector and repeated external ID isolate exact original questions",async()=>{
    await navigate(query(scenario.batch_ids[0]));
    assert.equal(await evaluate("document.documentElement.dir"),"rtl");
    assert.equal(await evaluate("document.querySelectorAll('#stored-batch option').length"),2);
    for(let index=0;index<2;index++){
      if(index===1)await navigate(query(scenario.batch_ids[0]));
      await evaluate(`document.querySelector('#stored-batch').value=${JSON.stringify(scenario.batch_ids[index])};document.querySelector('#stored-q').value=${JSON.stringify(scenario.repeated_external_id)};document.querySelector('#stored-q').focus()`);
      await submit();assert.equal(await evaluate("document.querySelectorAll('#wave7-persisted article').length"),1);
      await click("#wave7-persisted article h2 a");
      assert.equal(await evaluate("document.querySelector('#wave7-persisted article p.original-text').textContent"),scenario.original_questions[index]);
      assert.equal(await evaluate("new URL(location.href).searchParams.get('batch')"),scenario.batch_ids[index]);
    }
    await screenshot("persisted-desktop.png");
  }],
  ["filter/page/detail/return/back/forward/reload preserve real GET state",async()=>{
    await navigate(query(scenario.batch_ids[0]));
    await evaluate("document.querySelector('#stored-intake').value='BLOCKED_INVALID';document.querySelector('#stored-page-size').value='1';document.querySelector('#stored-q').value='اصطناعي';document.querySelector('#stored-q').focus()");
    await submit();await click('#wave7-persisted a[rel="next"]');
    const saved=await evaluate("location.href");assert.equal(new URL(saved).searchParams.get("page"),"2");
    await click("#wave7-persisted article h2 a");assert.match(await body(),/BLOCKED_INVALID/);
    for(const [key,value] of Object.entries({batch:scenario.batch_ids[0],q:"اصطناعي",intake_status:"BLOCKED_INVALID",page_size:"1",page:"2"}))assert.equal(await evaluate(`new URL(location.href).searchParams.get(${JSON.stringify(key)})`),value);
    await returnToList();assert.equal(await evaluate("location.href"),saved);
    await backForward("back");await backForward("forward");await reload();
    assert.equal(await evaluate("location.href"),saved);assert.equal(await evaluate("document.querySelector('#stored-intake').value"),"BLOCKED_INVALID");
  }],
  ["blocked/null rows, missing/invalid media and unresolved references remain visible",async()=>{
    await navigate(scenario.blocked_detail_path);assert.equal(await evaluate("document.querySelector('#wave7-persisted pre.original-text').textContent"),"null");
    assert.match(await body(),/BLOCKED_INVALID/);
    await navigate(scenario.missing_media_detail_path);assert.match(await body(),/غير مرفق/);
    await navigate(scenario.invalid_media_detail_path);assert.match(await body(),/http:\/\/example.invalid\/x/);
    await navigate(scenario.unresolved_detail_path);assert.match(await body(),/UNVERIFIED/);assert.match(await body(),/لا يوجد استشهاد موثق/);
    assert.equal(await evaluate("document.querySelectorAll('video,audio,source,iframe,a[href*=\"example.invalid\"]').length"),0);
  }],
  ["persisted review state/events and verified reference are distinct",async()=>{
    await navigate(scenario.reviewed_detail_path);const text=await body();
    assert.match(text,/READY_FOR_EDITOR/);assert.match(text,/REVIEWED_INTERNAL/);assert.match(text,/VERIFIED/);
    for(const reason of scenario.event_reasons)assert.ok(text.includes(reason));
    await reload();assert.match(await body(),/REVIEWED_INTERNAL/);
  }],
  ["new process replay and competing review services persist once before reload",async()=>{
    for(let index=0;index<2;index++){
      const replay=await child("replay",["--key",scenario.batch_keys[index]]);
      assert.equal(replay.exit,0);assert.equal(replay.result.decision,"REPLAY");assert.equal(replay.result.batch_id,scenario.batch_ids[index]);
    }
    await navigate(scenario.detail_paths[1]);assert.match(await body(),/UNREVIEWED/);
    const race=await Promise.all([child("start-review",["--item",scenario.review_target_id]),child("start-review",["--item",scenario.review_target_id])]);
    assert.deepEqual(race.map(result=>result.exit).sort(),[0,3]);
    assert.equal(race.find(result=>result.exit===3).result.code,"REVIEW_CONFLICT");
    for(let index=0;index<2;index++){
      const first=await child("inspect",["--key",scenario.batch_keys[index]]),second=await child("inspect",["--key",scenario.batch_keys[index]]);
      assert.deepEqual(first.result,second.result);assert.equal(first.result.event_count,index===0?4:1);
      assert.equal(first.result.items[6].question_original,scenario.original_questions[index]);
    }
    await reload();assert.match(await body(),/IN_REVIEW/);assert.match(await body(),/E6 synthetic browser race/);
  }],
  ["390 and 320 mobile native search/detail/return retain chosen batch",async()=>{
    for(const width of [390,320]){
      await cdp.send("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:true});
      await navigate(query(scenario.batch_ids[1]));
      await evaluate(`document.querySelector('#stored-q').value=${JSON.stringify(scenario.repeated_external_id)};document.querySelector('#stored-q').focus()`);
      await submit();await click("#wave7-persisted article h2 a");
      assert.equal(await evaluate("document.querySelector('#wave7-persisted article p.original-text').textContent"),scenario.original_questions[1]);
      assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
      await screenshot(`persisted-mobile-${width}.png`);await returnToList();
      assert.equal(await evaluate("document.querySelector('#stored-batch').value"),scenario.batch_ids[1]);
    }
  }],
  ["empty/error recovery and rapid navigation never show another batch detail",async()=>{
    await navigate(query(scenario.batch_ids[0],{q:"E6-NO-MATCH"}));assert.match(await body(),/لا توجد سجلات مطابقة/);
    await navigate(query(scenario.batch_ids[0],{page:"0"}));assert.match(await body(),/غير صالح/);
    await backForward("back");assert.match(await body(),/لا توجد سجلات مطابقة/);
    await Promise.allSettled(scenario.detail_paths.map(target=>cdp.send("Page.navigate",{url:origin+target})));
    await wait(`new URL(location.href).searchParams.get('batch')===${JSON.stringify(scenario.batch_ids[1])} && document.readyState==='complete'`);
    assert.equal(await evaluate("document.querySelector('#wave7-persisted article p.original-text').textContent"),scenario.original_questions[1]);
  }],
  ["no browser console/runtime errors, writes, external traffic or media",async()=>{
    assert.deepEqual(report.console_errors,[]);assert.deepEqual(report.exceptions,[]);assert.deepEqual(report.unwanted_requests,[]);
    assert.ok(report.requests.length>0);assert.ok(report.requests.every(request=>["GET","HEAD"].includes(request.method)));
  }],
];
report.tests=cases.map(([name])=>({name,result:"NOT_RUN"}));
try{
  assert.equal(process.versions.node.split(".")[0],"24");
  const response=await fetch(origin+query(scenario.batch_ids[0]),{redirect:"error",signal:AbortSignal.timeout(10000)});
  assert.equal(response.status,200);assert.ok((await response.text()).includes('id="wave7-persisted"'));
  report.http_preflight.push({path:route,status:200});
  for(const name of ["catalog.js","django-api.mjs","tree.js","catalog.css","style.css"]){
    const asset=await fetch(origin+"/assets/reference/"+name,{redirect:"error",signal:AbortSignal.timeout(10000)});
    assert.equal(asset.status,200);const mime=(asset.headers.get("content-type")??"").split(";")[0];
    assert.ok((name.endsWith("css")?["text/css"]:["text/javascript","application/javascript"]).includes(mime));
    assert.deepEqual(Buffer.from(await asset.arrayBuffer()),await readFile(path.join(root,"apps/reference/static/reference",name)));
    report.asset_preflight.push({name,status:200,mime,result:"PASS"});
  }
  const stylesheet=await fetch(origin+"/dev/editorial-preview/style.css",{redirect:"error",signal:AbortSignal.timeout(10000)});
  assert.equal(stylesheet.status,200);assert.equal(stylesheet.headers.get("content-type").split(";")[0],"text/css");
  assert.deepEqual(Buffer.from(await stylesheet.arrayBuffer()),await readFile(path.join(root,"apps/editorial_demo/preview.css")));
  report.asset_preflight.push({name:"editorial preview.css",status:200,mime:"text/css",result:"PASS"});
  phase="browser-startup";
  browser=spawn(executable,["--headless=new","--no-first-run","--no-default-browser-check","--disable-background-networking","--disable-component-update","--disable-sync","--remote-debugging-address=127.0.0.1","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],{stdio:["ignore","ignore","pipe"]});
  let launchError;browser.on("error",error=>{launchError=error;});browser.stderr.on("data",data=>{stderr=(stderr+data).slice(-2000);});
  let port;await until(async()=>{if(launchError)throw launchError;if(browser.exitCode!==null||browser.signalCode!==null)throw Error("Protected browser exited before DevTools");try{port=Number((await readFile(path.join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]);return !!port;}catch{return false;}},"DevTools");
  const tabs=await fetch(`http://127.0.0.1:${port}/json/list`).then(result=>result.json());
  socket=new WebSocket(tabs.find(tab=>tab.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true});});
  cdp=new CDP(socket,message=>{
    if(message.method==="Page.loadEventFired")loads++;
    if(message.method==="Runtime.exceptionThrown")report.exceptions.push(message.params.exceptionDetails.text);
    if(message.method==="Runtime.consoleAPICalled"&&message.params.type==="error")report.console_errors.push("console.error");
    if(message.method==="Fetch.requestPaused"){
      const {requestId,request,resourceType}=message.params,url=new URL(request.url),trace={method:request.method,path:url.pathname+url.search,type:resourceType};report.requests.push(trace);
      const allowed=permittedRequest(request,origin)&&resourceType!=="Media";if(!allowed)report.unwanted_requests.push(trace);
      cdp.send(allowed?"Fetch.continueRequest":"Fetch.failRequest",allowed?{requestId}:{requestId,errorReason:"BlockedByClient"}).catch(error=>report.exceptions.push(error.message));
    }
  });
  report.browser=await cdp.send("Browser.getVersion");phase="interactions";
  for(const domain of ["Page","Runtime","Network"])await cdp.send(domain+".enable");
  await cdp.send("Fetch.enable",{patterns:[{urlPattern:"*"}]});
  await cdp.send("Emulation.setDeviceMetricsOverride",{width:1280,height:900,deviceScaleFactor:1,mobile:false});
  for(let index=0;index<cases.length;index++){
    try{await cases[index][1]();report.tests[index].result="PASS";}
    catch(error){report.tests[index].result="FAIL";report.tests[index].error=error.message;await screenshot(`persisted-failure-${index+1}.png`).catch(()=>{});}
  }
  report.result=report.tests.some(test=>test.result==="FAIL")?"FAIL":"PASS";
}catch(error){report.result=phase==="browser-startup"?"BLOCKED":"FAIL";report.blocker=error.message;report.phase=phase;report.browser_stderr=stderr.replaceAll(profile,"<temporary-profile>");}
finally{
  socket?.close();cdp?.close();if(browser&&browser.exitCode===null&&browser.signalCode===null){browser.kill();await Promise.race([new Promise(resolve=>browser.once("exit",resolve)),pause(3000)]);}
  await rm(profile,{recursive:true,force:true,maxRetries:3,retryDelay:100});
  report.counts=Object.fromEntries(["PASS","FAIL","NOT_RUN"].map(status=>[status,report.tests.filter(test=>test.result===status).length]));report.counts.SKIP=0;
  await writeFile(path.join(artifacts,"workflow-result.json"),JSON.stringify(report,null,2)+"\n");
}
console.log(JSON.stringify({result:report.result,counts:report.counts,blocker:report.blocker,artifacts}));
process.exitCode=report.result==="PASS"?0:report.result==="BLOCKED"?2:1;
