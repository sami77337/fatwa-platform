// Real Chrome/CDP, actual Django SSR/API/static routes, no HTML overlay and no npm deps.
import assert from "node:assert/strict";
import {spawn, execFileSync} from "node:child_process";
import {mkdir, mkdtemp, readFile, writeFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {CDP, loopbackOrigin, permittedRequest} from "./cdp.mjs";
import {reviewBatchCase} from "./review_batches.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const origin = loopbackOrigin(process.argv[2]);
const executable = process.env.E6_BROWSER ?? "/usr/bin/chromium";
const artifacts = path.resolve(process.env.E6_ARTIFACTS ?? path.join(root, "docs/dev/e6/artifacts/latest"));
await mkdir(artifacts, {recursive:true});
const git = (...args) => execFileSync("git", args, {cwd:root, encoding:"utf8"}).trim();
const report = {
  schema: "fatwa.e6.browser.v1", timestamp: new Date().toISOString(),
  scope: "synthetic Django/PostgreSQL only; not owner/source acceptance", result:"NOT_RUN",
  sha:git("rev-parse", "HEAD"), dirty_paths:git("status", "--porcelain").split("\n").filter(Boolean),
  command:["node", "tests/acceptance/wave6/browser.mjs", origin],
  environment:{node:process.version, platform:os.platform(), release:os.release(), architecture:os.arch()},
  tests:[], requests:[], console_errors:[], exceptions:[], unwanted_requests:[],
  source_acceptance:"NOT_RUN", assembled_acceptance:"NOT_RUN", screenshots:[],
  review_batch_acceptance:"NOT_RUN", asset_preflight:[],
};
try { report.environment.browser = execFileSync(executable, ["--version"], {encoding:"utf8"}).trim(); }
catch { report.environment.browser = "unavailable"; }

let browser, socket, cdp, stderr = "", injectSearchFailure = false, documentsLoaded = 0;
let phase = "service-preflight";
const profile = await mkdtemp(path.join(os.tmpdir(), "fatwa-e6-browser-"));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, milliseconds=12000) {
  const deadline=Date.now()+milliseconds;
  while (Date.now()<deadline) { if (await check()) return; await pause(50); }
  throw Error("Timed out: " + label);
}
const evaluate = expression => cdp.evaluate(expression);
const wait = expression => until(() => evaluate(expression), expression);
const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
const text = () => evaluate("document.body.innerText");
async function navigate(route) {
  const previous = documentsLoaded;
  await cdp.send("Page.navigate", {url:origin+route});
  await until(() => documentsLoaded > previous, "document load");
  await wait(`location.pathname===${JSON.stringify(route.split("?")[0])} && document.readyState==='complete'`);
}
async function reload() {
  const previous=documentsLoaded;
  await cdp.send("Page.reload");
  await until(() => documentsLoaded > previous, "document reload");
  await wait("document.readyState==='complete'");
}
const catalogReady = () => wait("document.querySelector('#interactive-catalog')?.hidden===false && document.querySelector('#tree-region').getAttribute('aria-busy')==='false' && !!document.querySelector('[role=treeitem]')");
async function search(query, mode="normalized", filters={}) {
  await evaluate(`document.querySelector('#search-query').value=${JSON.stringify(query)};
    document.querySelector('#search-mode').value=${JSON.stringify(mode)};
    document.querySelector('#search-depth').value=${JSON.stringify(filters.depth ?? "")};
    document.querySelector('#search-has_children').value=${JSON.stringify(filters.children ?? "")};
    document.querySelector('#search-scope').value=${JSON.stringify(filters.root ?? "")};
    document.querySelector('#search-form').requestSubmit()`);
  await wait("document.querySelector('#search-results').getAttribute('aria-busy')==='false'");
}
async function key(key, code) {
  await cdp.send("Input.dispatchKeyEvent", {type:"keyDown", key, windowsVirtualKeyCode:code,
    ...(key === "Enter" ? {code:"Enter",text:"\r",unmodifiedText:"\r"} : {})});
  await cdp.send("Input.dispatchKeyEvent", {type:"keyUp", key, windowsVirtualKeyCode:code});
}
async function screenshot(name) {
  const result = await cdp.send("Page.captureScreenshot", {format:"png", captureBeyondViewport:true});
  await writeFile(path.join(artifacts,name), Buffer.from(result.data,"base64"));
  report.screenshots.push(name);
}
async function history(direction) {
  const previous = await evaluate("location.href");
  await evaluate(`history.${direction}()`);
  await wait(`location.href!==${JSON.stringify(previous)}`);
  await wait("document.readyState==='complete'");
}

const cases = [
  ["catalog actual SSR and desktop keyboard", async () => {
    await navigate("/fiqh"); await catalogReady();
    assert.equal(await evaluate("document.documentElement.dir"), "rtl");
    assert.equal(await evaluate("document.querySelectorAll('select[name=edition]').length"), 0);
    assert.doesNotMatch(await text(), /طبعة اصطناعية داخلية|sha256|bbbbbbbbbbbb/);
    await evaluate("document.querySelector('[role=treeitem]').focus()");
    await key("ArrowRight",39); await key("ArrowLeft",37);
    await wait("document.querySelectorAll('[role=treeitem]').length>1");
    await key("End",35);
    assert.equal(await evaluate("document.activeElement===[...document.querySelectorAll('[role=treeitem]')].at(-1)"),true);
    await key("Home",36); await key("Tab",9);
    assert.ok(await evaluate("document.activeElement!==document.body"));
    await screenshot("catalog-desktop.png");
  }],
  ["catalog three Arabic search modes preserve original marks", async () => {
    await navigate("/fiqh"); await catalogReady();
    for (const [mode,query] of [["exact","كِتَابُ الطَّهَارَةِ"],["literal","كِتَابُ الطَّهَارَةِ"],["normalized","كتاب الطهارة"]]) {
      await search(query,mode);
      assert.equal(await evaluate("document.querySelectorAll('#search-results li a').length"),1);
      assert.match(await evaluate("document.querySelector('#search-results').innerText"),/كِتَابُ الطَّهَارَةِ/);
    }
  }],
  ["catalog filters, page, detail, history, reload and clear", async () => {
    await navigate("/fiqh"); await catalogReady();
    await search("باب","normalized",{root:"1",depth:"2",children:"false"});
    assert.equal(await evaluate("document.querySelectorAll('#search-results li a').length"),20);
    await evaluate("[...document.querySelectorAll('#search-results button')].find(e=>e.textContent==='نتائج تالية').click()");
    await wait("new URL(location.href).searchParams.get('offset')==='20'");
    const saved=await evaluate("location.href");
    await click("#search-results li a"); await wait("location.pathname.startsWith('/fiqh/nodes/')");
    await wait("document.querySelector('#tree-region').getAttribute('aria-busy')==='false'");
    assert.match(await evaluate("document.querySelector('#reference-content').innerText"),/باب اصطناعي/);
    await history("back"); assert.equal(await evaluate("location.href"),saved);
    await history("forward"); await history("back");
    // Follow PR47's actual basic link and assert filter/page identity survives.
    const basic=await evaluate("document.querySelector('#basic-link').getAttribute('href')");
    for (const [name,value] of [["q","باب"],["depth","2"],["has_children","false"],["offset","20"]]) assert.equal(new URL(basic,origin).searchParams.get(name),value);
    // E4 deliberately renders reloaded search bookmarks as native SSR pages.
    await reload(); await wait("!!document.querySelector('#query') && !!document.querySelector('.heading-list')");
    assert.equal(await evaluate("location.href"),saved);
    for (const [selector,value] of [["#query","باب"],["#mode","normalized"],["#basic-depth","2"],["#basic-has_children","false"],["input[name=root]","1"]]) {
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector)}).value`),value);
    }
    assert.equal(await evaluate("document.querySelectorAll('.heading-list > li > a').length"),20);
    assert.match(await evaluate("document.querySelector('.heading-list > li > a').textContent"),/باب اصطناعي للطهارة 21/);
    await click(".heading-list > li > a"); await wait("!!document.querySelector('.basic-reference')");
    assert.match(await evaluate("document.querySelector('.selected-title').textContent"),/باب اصطناعي للطهارة 21/);
    await evaluate("[...document.querySelectorAll('a')].find(a=>a.textContent==='العودة إلى نتائج البحث').click()");
    await wait("location.pathname==='/fiqh' && !!document.querySelector('.heading-list > li > a')");
    for (const [name,value] of [["q","باب"],["mode","normalized"],["root","1"],["depth","2"],["has_children","false"],["offset","20"]]) {
      assert.equal(await evaluate(`new URL(location.href).searchParams.get(${JSON.stringify(name)})`),value);
    }
    await evaluate("[...document.querySelectorAll('a')].find(a=>a.textContent==='مسح البحث والمرشحات').click()");
    await wait("!new URL(location.href).searchParams.has('q') && document.querySelector('#query')?.value===''");
    assert.equal(await evaluate("document.querySelector('#basic-depth').value+document.querySelector('#basic-has_children').value"),"");
    await navigate("/fiqh"); await catalogReady();
    await search("باب","normalized",{root:"1",depth:"2",children:"false"});
    await click("#clear-search");
    assert.equal(await evaluate("document.querySelector('#search-query').value"),"");
    assert.equal(await evaluate("new URL(location.href).searchParams.has('q')"),false);
    assert.equal(await evaluate("document.activeElement.id"),"search-query");
    assert.equal(await evaluate("document.querySelector('#search-depth').value+document.querySelector('#search-has_children').value+document.querySelector('#search-scope').value"),"");
    assert.equal(new URL(await evaluate("document.querySelector('#basic-link').getAttribute('href')"),origin).searchParams.has("q"),false);
  }],
  ["catalog empty-query filters are applied", async () => {
    await navigate("/fiqh"); await catalogReady();
    await search("","normalized",{depth:"2",children:"false"});
    assert.equal(await evaluate("document.querySelectorAll('#search-results li a').length"),20);
    const link=await evaluate("document.querySelector('#basic-link').getAttribute('href')");
    await navigate(link);
    assert.match(await evaluate("document.querySelector('.heading-list').innerText"),/باب اصطناعي/);
    assert.doesNotMatch(await evaluate("document.querySelector('.heading-list').innerText"),/كِتَابُ الطَّهَارَةِ/);
  }],
  ["catalog empty results and recoverable service error", async () => {
    await navigate("/fiqh"); await catalogReady(); await search("غيرموجود");
    assert.match(await evaluate("document.querySelector('#search-results').innerText"),/لم نعثر/);
    injectSearchFailure=true; await search("باب");
    await wait("!!document.querySelector('#error button')");
    await click("#error button"); await wait("!!document.querySelector('#search-results li a')");
    assert.equal(await evaluate("document.querySelector('#error').innerText"),"");
  }],
  ["review filter, pagination, detail, return and browser history", async () => {
    await navigate("/dev/editorial-preview/pipeline");
    await evaluate("document.querySelector('#page-size').value='1';document.querySelector('#q').focus()");
    await key("Enter",13); await wait("new URL(location.href).searchParams.get('page_size')==='1'");
    await click('a[rel="next"]'); await wait("new URL(location.href).searchParams.get('page')==='2'");
    const saved=await evaluate("location.href"); await click("article h2 a");
    await wait("new URL(location.href).searchParams.get('row')==='2' && !!document.querySelector('article h3')");
    assert.match(await text(),/إحالة غير محسومة/);
    await evaluate("[...document.querySelectorAll('a')].find(a=>a.textContent.includes('العودة إلى القائمة المصفاة')).click()");
    await wait("location.pathname.endsWith('/pipeline')"); assert.equal(await evaluate("location.href"),saved);
    await history("back"); await history("forward");
    await reload(); await wait("!!document.querySelector('article h2 a')");
    assert.equal(await evaluate("new URL(location.href).searchParams.get('page')"),"2");
  }],
  ["review missing/invalid media, unresolved references, empty and invalid queries", async () => {
    for (const [issue,expected] of [["media_missing","رابط المقطع ناقص"],["media_invalid","رابط المقطع غير صالح"],["reference_unverified","SYN-P02"]]) {
      await navigate("/dev/editorial-preview/pipeline");
      await evaluate(`document.querySelector('#issue').value=${JSON.stringify(issue)};document.querySelector('form').requestSubmit()`);
      await wait(`new URL(location.href).searchParams.get('issue')===${JSON.stringify(issue)}`);
      assert.ok((await text()).includes(expected));
      assert.equal(await evaluate("document.querySelectorAll('video,audio,iframe,source').length"),0);
      await click("article h2 a"); await wait("!!document.querySelector('article h3')");
      assert.equal(await evaluate("document.querySelectorAll('a[href*=\"example.invalid\"]').length"),0);
    }
    await navigate("/dev/editorial-preview/pipeline?q=غيرموجود"); assert.match(await text(),/لا توجد سجلات مطابقة/);
    await navigate("/dev/editorial-preview/pipeline?page=0"); assert.match(await text(),/معايير تصفية غير صالحة/);
  }],
  ["narrow mobile catalog and connected review without horizontal overflow", async () => {
    for (const width of [390,320]) {
      await cdp.send("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:true});
      await navigate("/fiqh"); await catalogReady(); await search("باب");
      assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
      await screenshot(`catalog-mobile-${width}.png`);
      await navigate("/dev/editorial-preview/pipeline?page_size=1"); await click("article h2 a");
      await wait("!!document.querySelector('article h3')");
      assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
      await screenshot(`review-mobile-${width}.png`);
    }
  }],
  ["no runtime exceptions, console errors, external/media requests or writes", async () => {
    assert.deepEqual(report.console_errors,[]); assert.deepEqual(report.exceptions,[]);
    assert.deepEqual(report.unwanted_requests,[]);
    assert.ok(report.requests.length>0);
    assert.ok(report.requests.every(r=>["GET","HEAD"].includes(r.method)));
    assert.ok(report.requests.every(r=>!/[.](mp4|mp3|webm|ogg)(?:[?]|$)/i.test(r.path)));
  }],
];
if (process.env.E6_REVIEW_BATCHES === "required") {
  cases.splice(-1, 0, reviewBatchCase({navigate, wait, evaluate, click, key, reload, history, text}));
}
report.tests=cases.map(([name])=>({name,result:"NOT_RUN"}));

try {
  assert.equal(process.versions.node.split(".")[0],"24");
  const inventory=await fetch(origin+"/api/v1/fiqh/books",{redirect:"error",signal:AbortSignal.timeout(10000)}).then(r=>r.json());
  assert.equal(inventory.items.length,1);
  assert.equal(inventory.items[0].work.source_namespace,"wave6-e6-synthetic");
  assert.equal(inventory.items[0].heading_count,47);
  for (const name of ["catalog.js","django-api.mjs","tree.js","style.css","catalog.css"]) {
    const response=await fetch(origin+"/assets/reference/"+name,{redirect:"error",signal:AbortSignal.timeout(10000)});
    assert.equal(response.status,200,"Asset HTTP status: "+name);
    const mime=(response.headers.get("content-type")??"").split(";")[0];
    assert.ok((name.endsWith(".css")?["text/css"]:["text/javascript","application/javascript"]).includes(mime),"Asset MIME: "+name);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()),await readFile(path.join(root,"apps/reference/static/reference",name)),"Asset bytes: "+name);
    report.asset_preflight.push({path:"/assets/reference/"+name,status:200,mime,result:"PASS"});
  }
  // Keep Chromium's sandbox enabled. No user overrides can add bypass flags.
  phase="browser-startup";
  browser=spawn(executable,["--headless=new","--no-first-run","--no-default-browser-check","--disable-background-networking","--disable-component-update","--disable-sync","--remote-debugging-address=127.0.0.1","--remote-debugging-port=0","--user-data-dir="+profile,"about:blank"],{stdio:["ignore","ignore","pipe"]});
  let launchError;
  browser.on("error",error=>{launchError=error;});
  browser.stderr.on("data",data=>{stderr=(stderr+data).slice(-4000);});
  let port;
  await until(async()=>{
    if (launchError) throw launchError;
    if (browser.exitCode!==null || browser.signalCode!==null) throw Error("Browser exited before DevTools: sandbox/startup gate blocked");
    try {port=Number((await readFile(path.join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]);return !!port;}catch{return false;}
  },"DevTools launch");
  const tabs=await fetch(`http://127.0.0.1:${port}/json/list`).then(r=>r.json());
  socket=new WebSocket(tabs.find(tab=>tab.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true});});
  cdp=new CDP(socket,message=>{
    if(message.method==="Page.loadEventFired") documentsLoaded++;
    if(message.method==="Runtime.exceptionThrown") report.exceptions.push(message.params.exceptionDetails.text);
    if(message.method==="Runtime.consoleAPICalled" && message.params.type==="error") report.console_errors.push(message.params.args.map(arg=>arg.value??arg.description).join(" "));
    if(message.method==="Fetch.requestPaused") {
      const {requestId,request,resourceType}=message.params;
      const target=new URL(request.url);
      const trace={method:request.method,path:target.pathname+target.search,type:resourceType};
      report.requests.push(trace);
      let action;
      if(!permittedRequest(request,origin) || resourceType==="Media") {
        report.unwanted_requests.push({...trace,origin:target.origin});
        action=cdp.send("Fetch.failRequest",{requestId,errorReason:"BlockedByClient"});
      } else if(injectSearchFailure && target.pathname==="/api/v1/fiqh/search") {
        injectSearchFailure=false; trace.injected_status=503;
        action=cdp.send("Fetch.fulfillRequest",{requestId,responseCode:503,responseHeaders:[{name:"Content-Type",value:"application/json"}],body:Buffer.from('{"kind":"SOURCE_BOOK_TOC_NOT_FATWAS","error":"catalog_unavailable"}').toString("base64")});
      } else action=cdp.send("Fetch.continueRequest",{requestId});
      action.catch(error=>report.exceptions.push(error.message));
    }
  });
  report.browser=await cdp.send("Browser.getVersion");
  phase="browser-interactions";
  for(const domain of ["Page","Runtime","Network"]) await cdp.send(domain+".enable");
  await cdp.send("Fetch.enable",{patterns:[{urlPattern:"*"}]});
  await cdp.send("Emulation.setDeviceMetricsOverride",{width:1280,height:900,deviceScaleFactor:1,mobile:false});
  for(let index=0;index<cases.length;index++) {
    const [name,run]=cases[index];
    try {await run();report.tests[index].result="PASS";console.log("PASS "+name);}
    catch(error) {
      report.tests[index]={name,result:"FAIL",error:error.message};
      report.tests[index].diagnostic = await evaluate(`({url:location.href,title:document.title,
        ready:document.readyState,interactiveHidden:document.querySelector('#interactive-catalog')?.hidden,
        treeBusy:document.querySelector('#tree-region')?.getAttribute('aria-busy'),
        body:document.body.innerText.slice(0,5000),focus:document.activeElement?.outerHTML?.slice(0,500)})`).catch(()=>null);
      console.log("DIAGNOSTIC "+JSON.stringify(report.tests[index].diagnostic));
      await screenshot(`failure-${index+1}.png`).catch(()=>{});
      console.log("FAIL "+name+": "+error.message);
    }
  }
  report.result=report.tests.some(t=>t.result==="FAIL")?"FAIL":"PASS";
  report.review_batch_acceptance=report.tests.find(t=>t.name.startsWith("PR51 "))?.result??"NOT_RUN";
}catch(error){report.result=phase==="browser-startup"?"BLOCKED":"FAIL";report.blocker=error.message;report.phase=phase;report.browser_stderr=stderr.replaceAll(profile,"<temporary-profile>").slice(-2000);}
finally {
  socket?.close();cdp?.close();
  if(browser && browser.exitCode===null && browser.signalCode===null) {
    browser.kill(); await Promise.race([new Promise(resolve=>browser.once("exit",resolve)),pause(3000)]);
  }
  await rm(profile,{recursive:true,force:true,maxRetries:3,retryDelay:100});
  report.counts=Object.fromEntries(["PASS","FAIL","NOT_RUN"].map(status=>[status,report.tests.filter(t=>t.result===status).length]));
  report.counts.SKIP=0;
  await writeFile(path.join(artifacts,"browser-result.json"),JSON.stringify(report,null,2)+"\n");
}
console.log(JSON.stringify({result:report.result,counts:report.counts,blocker:report.blocker,artifacts}));
console.log("E6_BROWSER_EVIDENCE "+JSON.stringify({sha:report.sha,dirty_paths:report.dirty_paths,
  browser:report.browser,environment:report.environment,result:report.result,counts:report.counts,
  tests:report.tests,asset_preflight:report.asset_preflight,screenshots:report.screenshots,
  request_count:report.requests.length,console_errors:report.console_errors,
  exceptions:report.exceptions,unwanted_requests:report.unwanted_requests}));
process.exitCode=report.result==="PASS"?0:report.result==="BLOCKED"?2:1;
