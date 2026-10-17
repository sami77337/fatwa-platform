// Baseline ONLY. Mandatory persisted acceptance is a separate failing integration gate.
import assert from "node:assert/strict";
import {spawn,execFileSync} from "node:child_process";
import {mkdir,mkdtemp,readFile,writeFile,rm} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import path from "node:path";
import os from "node:os";
import {CDP,loopbackOrigin,permittedRequest} from "./cdp.mjs";
import {dispatchKey} from "./keyboard.mjs";

const root=fileURLToPath(new URL("../../../",import.meta.url));
const origin=loopbackOrigin(process.argv[2]);
const executable=process.env.E6_BROWSER??"/usr/bin/chromium";
const artifacts=path.resolve(process.env.E6_WAVE7_ARTIFACTS??"/tmp/e6-wave7-browser");
await mkdir(artifacts,{recursive:true});
const git=(...args)=>execFileSync("git",args,{cwd:root,encoding:"utf8"}).trim();
const report={schema:"fatwa.e6.wave7.browser-baseline.v1",sha:git("rev-parse","HEAD"),
  dirty_paths:git("status","--porcelain").split("\n").filter(Boolean),
  scope:"Actual synthetic Django/PG catalog baseline ONLY",result:"NOT_RUN",tests:[],
  persisted_workflow:"NOT_RUN",source_acceptance:"NOT_RUN",asset_preflight:[],screenshots:[],
  environment:{node:process.version,platform:os.platform(),release:os.release()},
  command:["node","tests/acceptance/wave7/browser.mjs",origin],
  console_errors:[],exceptions:[],requests:[],unwanted_requests:[]};
try{report.environment.browser=execFileSync(executable,["--version"],{encoding:"utf8"}).trim();}
catch{report.environment.browser="unavailable";}
let browser,socket,cdp,stderr="",phase="service-preflight",loads=0;
const profile=await mkdtemp(path.join(os.tmpdir(),"fatwa-wave7-e6-"));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label){const end=Date.now()+12000;while(Date.now()<end){if(await check())return;await pause(40);}throw Error("Timed out: "+label);}
const evaluate=expression=>cdp.evaluate(expression);
const wait=expression=>until(()=>evaluate(expression),expression);
async function navigate(route){const before=loads;await cdp.send("Page.navigate",{url:origin+route});await until(()=>loads>before,"document load");await wait("document.readyState==='complete'");}
const ready=()=>wait("document.querySelector('#interactive-catalog')?.hidden===false && document.querySelector('#tree-region').getAttribute('aria-busy')==='false' && !!document.querySelector('[role=treeitem]')");
const key=(key,code)=>dispatchKey(cdp,key,code);
async function screenshot(name){const result=await cdp.send("Page.captureScreenshot",{format:"png",captureBeyondViewport:true});await writeFile(path.join(artifacts,name),Buffer.from(result.data,"base64"));report.screenshots.push(name);}
const cases=[
  ["desktop actual catalog and native RTL keyboard",async()=>{
    await navigate("/fiqh");await ready();assert.equal(await evaluate("document.documentElement.dir"),"rtl");
    await evaluate("document.querySelector('[role=treeitem]').focus()");await key("ArrowRight",39);await key("ArrowLeft",37);
    await wait("document.querySelectorAll('[role=treeitem]').length===3");await key("End",35);
    assert.equal(await evaluate("document.activeElement===[...document.querySelectorAll('[role=treeitem]')].at(-1)"),true);
    await screenshot("baseline-desktop.png");
  }],
  ["search, actual detail, browser history and reload",async()=>{
    await navigate("/fiqh");await ready();
    await evaluate("document.querySelector('#search-query').value='باب';document.querySelector('#search-query').focus()");
    await key("Enter",13);await wait("document.querySelectorAll('#search-results li a').length===2");
    await evaluate("document.querySelector('#search-results li a').click()");await wait("location.pathname.startsWith('/fiqh/nodes/')");
    await ready();assert.match(await evaluate("document.querySelector('#reference-content').innerText"),/بابٌ اصطناعي/);
    await evaluate("history.back()");await wait("location.pathname==='/fiqh'");
    await evaluate("history.forward()");await wait("location.pathname.startsWith('/fiqh/nodes/')");
    const before=loads;await cdp.send("Page.reload");await until(()=>loads>before,"reload");await ready();
  }],
  ["390 and 320 mobile catalog search without overflow",async()=>{
    for(const width of [390,320]){
      await cdp.send("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:true});
      await navigate("/fiqh");await ready();
      assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
      await screenshot(`baseline-mobile-${width}.png`);
    }
  }],
  ["no console/runtime exceptions, external network, media or writes",async()=>{
    assert.deepEqual(report.console_errors,[]);assert.deepEqual(report.exceptions,[]);assert.deepEqual(report.unwanted_requests,[]);
    assert.ok(report.requests.length>0);assert.ok(report.requests.every(r=>["GET","HEAD"].includes(r.method)));
  }],
];
report.tests=cases.map(([name])=>({name,result:"NOT_RUN"}));
try{
  assert.equal(process.versions.node.split(".")[0],"24");
  const inventory=await fetch(origin+"/api/v1/fiqh/books",{redirect:"error",signal:AbortSignal.timeout(10000)}).then(r=>r.json());
  assert.equal(inventory.items.length,1);assert.equal(inventory.items[0].work.source_namespace,"wave7-synthetic-toc");assert.equal(inventory.items[0].heading_count,3);
  for(const name of ["catalog.js","django-api.mjs","tree.js","catalog.css","style.css"]){
    const response=await fetch(origin+"/assets/reference/"+name,{redirect:"error",signal:AbortSignal.timeout(10000)});
    assert.equal(response.status,200);const mime=(response.headers.get("content-type")??"").split(";")[0];
    assert.ok((name.endsWith("css")?["text/css"]:["text/javascript","application/javascript"]).includes(mime));
    assert.deepEqual(Buffer.from(await response.arrayBuffer()),await readFile(path.join(root,"apps/reference/static/reference",name)));
    report.asset_preflight.push({name,status:200,mime,result:"PASS"});
  }
  phase="browser-startup";
  browser=spawn(executable,["--headless=new","--no-first-run","--no-default-browser-check","--disable-background-networking","--disable-component-update","--disable-sync","--remote-debugging-address=127.0.0.1","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],{stdio:["ignore","ignore","pipe"]});
  let launchError;browser.on("error",error=>{launchError=error;});browser.stderr.on("data",data=>{stderr=(stderr+data).slice(-2000);});
  let port;await until(async()=>{if(launchError)throw launchError;if(browser.exitCode!==null||browser.signalCode!==null)throw Error("Protected browser exited before DevTools");try{port=Number((await readFile(path.join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]);return !!port;}catch{return false;}},"DevTools");
  const tabs=await fetch(`http://127.0.0.1:${port}/json/list`).then(r=>r.json());
  socket=new WebSocket(tabs.find(tab=>tab.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true});});
  cdp=new CDP(socket,message=>{
    if(message.method==="Page.loadEventFired")loads++;
    if(message.method==="Runtime.exceptionThrown")report.exceptions.push(message.params.exceptionDetails.text);
    if(message.method==="Runtime.consoleAPICalled"&&message.params.type==="error")report.console_errors.push("console.error");
    if(message.method==="Fetch.requestPaused"){
      const {requestId,request,resourceType}=message.params,url=new URL(request.url);
      const trace={method:request.method,path:url.pathname+url.search,type:resourceType};report.requests.push(trace);
      const allowed=permittedRequest(request,origin)&&resourceType!=="Media";
      if(!allowed)report.unwanted_requests.push(trace);
      cdp.send(allowed?"Fetch.continueRequest":"Fetch.failRequest",allowed?{requestId}:{requestId,errorReason:"BlockedByClient"}).catch(error=>report.exceptions.push(error.message));
    }
  });
  report.browser=await cdp.send("Browser.getVersion");phase="interactions";
  for(const domain of ["Page","Runtime","Network"])await cdp.send(domain+".enable");
  await cdp.send("Fetch.enable",{patterns:[{urlPattern:"*"}]});
  await cdp.send("Emulation.setDeviceMetricsOverride",{width:1280,height:900,deviceScaleFactor:1,mobile:false});
  for(let index=0;index<cases.length;index++){
    try{await cases[index][1]();report.tests[index].result="PASS";}
    catch(error){report.tests[index].result="FAIL";report.tests[index].error=error.message;await screenshot(`baseline-failure-${index+1}.png`).catch(()=>{});}
  }
  report.result=report.tests.some(test=>test.result==="FAIL")?"FAIL":"PASS_BASELINE_ONLY";
}catch(error){report.result=phase==="browser-startup"?"BLOCKED":"FAIL";report.blocker=error.message;report.phase=phase;report.browser_stderr=stderr.replaceAll(profile,"<temporary-profile>");}
finally{
  socket?.close();cdp?.close();if(browser&&browser.exitCode===null&&browser.signalCode===null){browser.kill();await Promise.race([new Promise(resolve=>browser.once("exit",resolve)),pause(3000)]);}
  await rm(profile,{recursive:true,force:true,maxRetries:3,retryDelay:100});
  report.counts=Object.fromEntries(["PASS","FAIL","NOT_RUN"].map(status=>[status,report.tests.filter(test=>test.result===status).length]));report.counts.SKIP=0;
  await writeFile(path.join(artifacts,"browser-result.json"),JSON.stringify(report,null,2)+"\n");
}
console.log(JSON.stringify({result:report.result,counts:report.counts,blocker:report.blocker,artifacts}));
process.exitCode=report.result==="PASS_BASELINE_ONLY"?0:report.result==="BLOCKED"?2:1;
