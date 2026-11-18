// Actual B6 entrypoint failure probes, not mocked observer-only assertions.
// The loopback fixture serves only preflight data; no Chrome/product PASS is claimed.
import test from "node:test";
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {createServer} from "node:http";
import {mkdtemp, readFile, writeFile, chmod, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const assets = new Map(await Promise.all(
  ["catalog.js", "django-api.mjs", "tree.js", "style.css", "catalog.css"].map(async name => [
    `/assets/reference/${name}`,
    {bytes:await readFile(path.join(root,"apps/reference/static/reference",name)),
      type:name.endsWith(".css")?"text/css":"text/javascript"},
  ]),
));

async function probe(mode) {
  const temporary = await mkdtemp(path.join(tmpdir(), "v14-b6-wiring-"));
  const artifacts = path.join(temporary,"artifacts");
  const executable = path.join(temporary,"synthetic-private-marker-browser");
  const audit = path.join(temporary,"launches.txt");
  const server = createServer((request,response) => {
    const asset = assets.get(request.url);
    if (asset) {response.writeHead(200,{"content-type":asset.type});response.end(asset.bytes);}
    else if (request.url === "/api/v1/fiqh/books") {
      response.writeHead(200,{"content-type":"application/json"});
      response.end(JSON.stringify({items:[{work:{source_namespace:"wave6-e6-synthetic"},heading_count:47}]}));
    } else {response.writeHead(404);response.end();}
  });
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  try {
    if (mode !== "missing") {
      await writeFile(executable, `#!${process.execPath}
const fs = require('node:fs');
if(process.argv.includes('--version')) {console.log('Synthetic failure probe; not Chrome');process.exit(0);}
fs.appendFileSync(process.env.V14_PROBE_AUDIT, 'launch\\n');
const profile=process.argv.find(arg=>arg.startsWith('--user-data-dir=')).split('=').slice(1).join('=');
if(process.env.V14_PROBE_MODE==='target') {
 const server=require('node:http').createServer((req,res)=>{res.setHeader('content-type','application/json');res.end('[]');});
 server.listen(0,'127.0.0.1',()=>fs.writeFileSync(require('node:path').join(profile,'DevToolsActivePort'),String(server.address().port)));
} else {setInterval(()=>{},1000);}
`);
      await chmod(executable,0o700);
    }
    const result = await new Promise((resolve,reject)=>{
      const child=spawn(process.execPath,["tests/acceptance/wave6/browser.mjs",origin],{
        cwd:root,
        env:{...process.env,E6_BROWSER:executable,E6_ARTIFACTS:artifacts,E6_REVIEW_BATCHES:"required",
          V14_PROBE_AUDIT:audit,V14_PROBE_MODE:mode},
        stdio:["ignore","pipe","pipe"],
      });
      let stdout="",stderr="";
      const deadline=setTimeout(()=>{child.kill("SIGKILL");reject(Error("Synthetic B6 probe exceeded test bound"));},30000);
      child.stdout.on("data",chunk=>{stdout+=chunk;});
      child.stderr.on("data",chunk=>{stderr+=chunk;});
      child.once("error",error=>{clearTimeout(deadline);reject(error);});
      child.once("exit",code=>{clearTimeout(deadline);resolve({code,stdout,stderr});});
    });
    const report=JSON.parse(await readFile(path.join(artifacts,"browser-result.json"),"utf8"));
    const line=result.stdout.split("\n").find(value=>value.startsWith("E6_BROWSER_EVIDENCE "));
    assert.ok(line,"actual entrypoint must emit its evidence line");
    const evidence=JSON.parse(line.slice("E6_BROWSER_EVIDENCE ".length));
    assert.equal(result.code,2,"failed startup remains mandatory exit2, never PASS");
    assert.equal(report.result,"BLOCKED");
    assert.deepEqual(report.counts,{PASS:0,FAIL:0,NOT_RUN:10,SKIP:0});
    assert.equal(report.asset_preflight.length,5);
    assert.deepEqual(evidence.startup_observations,report.startup_observations);
    const observations=report.startup_observations;
    assert.equal(observations.result,"BLOCKED");
    assert.equal(observations.root_cause,"ROOT_CAUSE_UNKNOWN");
    assert.equal(observations.port_poll_limit_ms,12000);
    const serialized=JSON.stringify(observations);
    for(const forbidden of [temporary,origin,"synthetic-private-marker", "stderr", "--user-data-dir", "webSocketDebuggerUrl"]) {
      assert.equal(serialized.includes(forbidden),false);
    }
    const launches=mode==="missing"?0:(await readFile(audit,"utf8")).trim().split("\n").length;
    assert.equal(launches,mode==="missing"?0:1,"no retry or second launch added");
    return {report,observations};
  } finally {
    await new Promise(resolve=>server.close(resolve));
    await rm(temporary,{recursive:true,force:true});
  }
}

test("actual B6 spawn failure emits bounded snapshot and retains BLOCKED",async()=>{
  const {observations}=await probe("missing");
  assert.equal(observations.events["spawn-error"].count,1);
  assert.equal(observations.events["spawned"].count,0);
  assert.equal(observations.events["websocket-open"].count,0);
  assert.deepEqual(observations.phases.map(row=>row.phase),["spawn","port-file"]);
});

test("actual unchanged port poll times out once and freezes before cleanup exit",{timeout:35000},async()=>{
  const {report,observations}=await probe("timeout");
  assert.equal(report.blocker,"Timed out: DevTools launch");
  assert.equal(observations.events.spawned.count,1);
  assert.ok(observations.events["port-missing"].count>0);
  assert.equal(observations.events["process-exit"].count,0,"cleanup exit must not rewrite startup snapshot");
  assert.ok(observations.elapsed_ms>=12000);
  assert.deepEqual(observations.phases.map(row=>row.phase),["spawn","port-file"]);
});

test("actual port and target discovery reach their recorded boundaries",async()=>{
  const {observations}=await probe("target");
  assert.equal(observations.events["port-ready"].count,1);
  assert.equal(observations.events["target-response"].count,1);
  assert.equal(observations.events["websocket-open"].count,0);
  assert.equal(observations.events["process-exit"].count,0);
  assert.deepEqual(observations.phases.map(row=>row.phase),["spawn","port-file","target-discovery","websocket"]);
});
