// Existing protected CDP transport, actual Django pages, no browser security bypass.
import assert from "node:assert/strict";
import {spawn, execFileSync} from "node:child_process";
import {mkdir, mkdtemp, readFile, writeFile, rm} from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import {fileURLToPath} from "node:url";
import {CDP, loopbackOrigin} from "../wave7/cdp.mjs";
import {dispatchKey} from "../wave7/keyboard.mjs";
import {allowedRequest, aggregateResult, catalogIdentity} from "./policy.mjs";
import {editorialCases} from "./editorial.mjs";
import {catalogCases} from "./catalog.mjs";
import {fast3Cases} from "./fast3.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const artifacts = path.resolve(process.env.FATWA_FASTBUILD_ARTIFACTS ?? path.join(os.tmpdir(),"fatwa-fastbuild-qa"));
const scope = process.argv[3] ?? "editorial";
assert.ok(["editorial","catalog"].includes(scope), "Explicit editorial or catalog scope required");
await mkdir(artifacts,{recursive:true});
const git = (...args) => execFileSync("git", args, {cwd:root,encoding:"utf8"}).trim();
const report = {schema:"fatwa.fastbuild.browser.v1", scope, result:"NOT_RUN", sha:git("rev-parse","HEAD"),
  dirty_paths:git("status","--porcelain").split("\n").filter(Boolean), fixtures:{
    wave7_payload_sha256:"cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb",
    serialized_history_intake_sha256:"75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0",
    catalog: "wave7-fixed-fabricated-fixture: 3 nodes, 1 root, depth 2; asserted hashes a*64/b*64"},
  tests:[], requests:[], violations:[], exceptions:[], console_errors:[], http_failures:[], screenshots:[],
  not_run:[scope==="editorial"?"PostgreSQL catalog (run --catalog separately)":"editorial (run default suite separately)","persisted workflow", "owner source ZIP acceptance"],
  environment:{node:process.version,platform:os.platform()},status:"NOT_DEPLOYED / GATES_HOLD / SCOPE_DEVIATION_HOLD"};
let origin, browser, socket, cdp, profile, loads=0, stderr="", phase="preflight", viewportWidth=1280;
// End before Python's outer timeout so the normal finally always gets cleanup time.
const watchdog=setTimeout(()=>{
  report.deadline_exceeded=true; socket?.close(); cdp?.close(); browser?.kill();
},180000);
const pause = ms => new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label) {
  const end=Date.now()+12000;
  while(Date.now()<end) {
    if(report.deadline_exceeded) throw Error("QA runner deadline exceeded");
    if(await check()) return; await pause(40);
  }
  throw Error("Timed out: "+label);
}
const evaluate = expression => cdp.evaluate(expression);
const wait = expression => until(()=>evaluate(expression),expression);
async function navigate(route,status=200) {
  const before=loads;
  // Network response is independently checked, including expected 400/404 recovery pages.
  expectedDocuments.set(origin+route.split("#")[0],status);
  const result=await cdp.send("Page.navigate",{url:origin+route});
  assert.equal(result.errorText,undefined);
  await until(()=>loads>before,"document load: "+route);
  await wait("document.readyState==='complete'");
  assert.equal(documentStatuses.get(origin+route.split("#")[0]),status,"document HTTP status");
}
const key=(name,code)=>dispatchKey(cdp,name,code);
async function focus(selector) {
  assert.equal(await evaluate(`!!document.querySelector(${JSON.stringify(selector)})`),true,"missing control: "+selector);
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).focus()`);
}
async function activate(selector) { await focus(selector); await key("Enter",13); }
async function type(selector,text) { await focus(selector); await cdp.send("Input.insertText",{text}); }
async function select(selector,steps) {
  await focus(selector); await key("Home",36);
  for(let index=0;index<steps;index++) await key("ArrowDown",40);
}
async function viewport(width) {
  viewportWidth=width;
  await cdp.send("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:width<600});
}
async function noOverflow() {
  await evaluate("new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))");
  const dimensions=await evaluate("({viewport:innerWidth,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})");
  assert.equal(dimensions.viewport,viewportWidth,"viewport meta must honor requested mobile width");
  assert.equal(dimensions.client,viewportWidth,"layout must honor requested mobile width");
  assert.ok(dimensions.scroll<=dimensions.client,"horizontal overflow: "+JSON.stringify(dimensions));
}
async function screenshot(name) {
  const {data}=await cdp.send("Page.captureScreenshot",{format:"png",captureBeyondViewport:true});
  await writeFile(path.join(artifacts,name),Buffer.from(data,"base64")); report.screenshots.push(name);
}
const expectedDocuments=new Map(),documentStatuses=new Map(), interceptions=new Set();
const h={navigate,evaluate,wait,key,focus,activate,type,select,viewport,noOverflow,screenshot,get cdp(){return cdp;}};
const cases=scope==="editorial"?editorialCases(h):catalogCases(h);
if(scope==="editorial") cases.push(...fast3Cases(h));
cases.push(["all observed browser requests are local read-only; no runtime or unexpected HTTP failures",async()=>{
  await Promise.all([...interceptions]);
  assert.ok(report.requests.length>0);
  assert.deepEqual(report.violations,[]); assert.deepEqual(report.exceptions,[]);
  assert.deepEqual(report.console_errors,[]); assert.deepEqual(report.http_failures,[]);
  assert.ok(report.requests.every(r=>["GET","HEAD"].includes(r.method)));
}]);
report.tests=cases.map(([name])=>({name,result:"NOT_RUN"}));
try {
  if(process.argv[4]==="--not-run") { phase="not-run"; throw Error(process.argv[5]??"guarded service unavailable"); }
  origin=loopbackOrigin(process.argv[2]);
  assert.ok(Number(process.versions.node.split(".")[0])>=24,"Node 24+ required");
  if(scope==="catalog") {
    const response=await fetch(origin+"/api/v1/fiqh/books",{redirect:"error",signal:AbortSignal.timeout(10000)});
    assert.equal(response.status,200,"synthetic catalog unavailable");
    assert.equal(catalogIdentity(await response.json()),true,"refuse non-synthetic catalog");
  } else {
    const response=await fetch(origin+"/dev/editorial-workbench/history",{redirect:"error",signal:AbortSignal.timeout(10000)});
    assert.equal(response.status,200);
    const html=await response.text();
    for(const hash of [report.fixtures.wave7_payload_sha256, report.fixtures.serialized_history_intake_sha256]) {
      const route=hash===report.fixtures.wave7_payload_sha256?"/dev/editorial-workbench/intake-7":null;
      const source=route?await fetch(origin+route,{redirect:"error",signal:AbortSignal.timeout(10000)}).then(r=>r.text()):html;
      assert.ok(source.includes(hash),"fixture hash mismatch");
    }
  }
  phase="browser-startup";
  const executable=process.env.FATWA_FASTBUILD_BROWSER ?? (process.platform==="win32"?"C:/Program Files/Google/Chrome/Application/chrome.exe":"/usr/bin/chromium");
  profile=await mkdtemp(path.join(os.tmpdir(),"fatwa-fastbuild-profile-"));
  browser=spawn(executable,["--headless=new","--no-first-run","--no-default-browser-check","--disable-background-networking","--disable-component-update","--disable-sync","--remote-debugging-address=127.0.0.1","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],{windowsHide:true,stdio:["ignore","ignore","pipe"]});
  let launchError; browser.on("error",error=>{launchError=error;});
  browser.stderr.on("data",data=>{stderr=(stderr+data).slice(-1500);});
  let port;
  await until(async()=>{
    if(launchError) throw launchError;
    if(browser.exitCode!==null||browser.signalCode!==null) throw Error("Protected browser exited before DevTools");
    try {port=Number((await readFile(path.join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]);return !!port;}catch{return false;}
  },"protected DevTools startup");
  const tabs=await fetch(`http://127.0.0.1:${port}/json/list`,{signal:AbortSignal.timeout(5000)}).then(r=>r.json());
  socket=new WebSocket(tabs.find(tab=>tab.type==="page").webSocketDebuggerUrl);
  let socketError;
  socket.addEventListener("error",()=>{socketError=Error("CDP WebSocket failed");});
  await until(()=>{if(socketError) throw socketError;return socket.readyState===WebSocket.OPEN;},"CDP WebSocket open");
  cdp=new CDP(socket,message=>{
    const p=message.params;
    if(message.method==="Page.loadEventFired") loads++;
    if(message.method==="Runtime.exceptionThrown") report.exceptions.push(p.exceptionDetails.text);
    if(message.method==="Runtime.consoleAPICalled"&&p.type==="error") report.console_errors.push("console.error");
    if(message.method==="Network.responseReceived") {
      const {response:r,type}=p;
      if(type==="Document") documentStatuses.set(r.url,r.status);
      if(r.status>=400 && r.url!==origin+"/favicon.ico" && expectedDocuments.get(r.url)!==r.status)
        report.http_failures.push({path:new URL(r.url).pathname,status:r.status});
    }
    if(message.method==="Fetch.requestPaused") {
      const allowed=allowedRequest(p.request,origin)&&p.resourceType!=="Media";
      const trace={method:p.request.method,path:new URL(p.request.url).pathname,type:p.resourceType};
      report.requests.push(trace); if(!allowed) report.violations.push(trace);
      const job=cdp.send(allowed?"Fetch.continueRequest":"Fetch.failRequest",allowed?{requestId:p.requestId}:{requestId:p.requestId,errorReason:"BlockedByClient"})
        .catch(error=>report.exceptions.push(error.message));
      interceptions.add(job); job.finally(()=>interceptions.delete(job));
    }
  });
  report.environment.browser=await cdp.send("Browser.getVersion");
  for(const domain of ["Page","Runtime","Network","Accessibility"]) await cdp.send(domain+".enable");
  await cdp.send("Fetch.enable",{patterns:[{urlPattern:"*"}]});
  await viewport(1280); phase="interactions";
  for(let index=0;index<cases.length;index++) {
    if(report.deadline_exceeded) throw Error("QA runner deadline exceeded");
    try {await cases[index][1]();report.tests[index].result="PASS";}
    catch(error) {report.tests[index].result="FAIL";report.tests[index].error=error.message;await screenshot(`${scope}-failure-${index+1}.png`).catch(()=>{});}
    console.log(report.tests[index].result+" "+cases[index][0]);
  }
  report.result=aggregateResult(report.tests);
} catch(error) {
  report.result=["browser-startup","not-run"].includes(phase)?"NOT_RUN":"FAIL";
  report.blocker=error.message; report.phase=phase;
  report.browser_stderr=profile?stderr.replaceAll(profile,"<temporary-profile>"):stderr;
} finally {
  clearTimeout(watchdog);
  socket?.close(); cdp?.close();
  if(browser&&browser.exitCode===null&&browser.signalCode===null) {
    browser.kill(); await Promise.race([new Promise(resolve=>browser.once("exit",resolve)),pause(3000)]);
  }
  if(profile) {
    const resolved=path.resolve(profile);
    assert.equal(path.dirname(resolved),path.resolve(os.tmpdir()));
    assert.ok(path.basename(resolved).startsWith("fatwa-fastbuild-profile-"));
    await rm(resolved,{recursive:true,force:true,maxRetries:5,retryDelay:200}).catch(()=>{report.cleanup="temporary profile retained";});
  }
  report.counts=Object.fromEntries(["PASS","FAIL","NOT_RUN"].map(result=>[result,report.tests.filter(t=>t.result===result).length]));
  await writeFile(path.join(artifacts,`${scope}-result.json`),JSON.stringify(report,null,2)+"\n");
  console.log(JSON.stringify({result:report.result,scope,counts:report.counts,report:path.join(artifacts,`${scope}-result.json`)}));
}
process.exitCode=report.result==="PASS"?0:report.result==="NOT_RUN"?2:1;
