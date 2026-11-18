import assert from "node:assert/strict";
import {access, mkdtemp, readFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {test} from "node:test";
import {ProtectedBrowser} from "../acceptance/fastbuild/startup.mjs";
import {runResearchBrowser} from "../research_bridge/startup.mjs";

const fixture = fileURLToPath(new URL("./delayed_peer.mjs", import.meta.url));

test("startup remains one capped deadline, with no extended run escape", async () => {
  assert.equal(new ProtectedBrowser({executable:process.execPath}).timeoutMs, 30000);
  for (const budget of [30001, Infinity, NaN, 0, -1])
    assert.throws(() => new ProtectedBrowser({startupTimeoutMs:budget}), RangeError);
  await assert.rejects(runResearchBrowser(() => assert.fail("must not run"), {
    runTimeoutMs:75001,
  }), RangeError);
});

test("websocket terminal stage does not mean the entire budget was spent there", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "fatwa-v13-startup-"));
  const record = path.join(directory, "peer.json");
  const observations = [];
  // Local instrumentation only. The actual inherited deadline and endpoint
  // validation are unchanged; no mocked successful browser/application journey.
  class ObservedBrowser extends ProtectedBrowser {
    async port() {
      const started = performance.now();
      try { return await super.port(); }
      finally { observations.push({phase:"port-file", elapsed:performance.now() - started}); }
    }
  }
  const browser = new ObservedBrowser({executable:process.execPath,
    args:[fixture, "delayed-socket-hang", record], startupTimeoutMs:2000});
  try {
    await assert.rejects(browser.start(), {code:"BROWSER_STARTUP_TIMEOUT", stage:"websocket"});
    assert.equal(browser.stage, "websocket");
    assert.ok(observations[0].elapsed >= 650, "earlier phase consumed part of shared budget");
    assert.ok(browser.elapsedMs >= 2000 && browser.elapsedMs < 4000);
    const cleanup = await browser.close();
    assert.deepEqual(cleanup, {result:"PASS", errors:[]});
    const launch = JSON.parse(await readFile(record, "utf8"));
    await assert.rejects(access(launch.profile), {code:"ENOENT"});
    assert.ok(launch.args.includes("--remote-debugging-address=127.0.0.1"));
    assert.equal(launch.args.some(arg => /no-sandbox|disable.*sandbox|disable-web-security/.test(arg)), false);
    console.log(JSON.stringify({scope:"synthetic lifecycle diagnostic only",
      total_startup_ms:browser.elapsedMs, port_file_ms:Math.round(observations[0].elapsed),
      terminal_stage:browser.stage, cleanup:"PASS", root_cause:"ROOT_CAUSE_UNKNOWN"}));
  } finally {
    await browser.close();
    await rm(directory, {recursive:true, force:true});
  }
});

test("the research wrapper retains NOT_RUN and performs no journey retry", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "fatwa-v13-startup-"));
  let calls = 0;
  try {
    const report = await runResearchBrowser(() => { calls++; }, {
      executable:process.execPath, args:[fixture, "delayed-socket-hang", path.join(directory, "peer.json")],
      startupTimeoutMs:2000,
    });
    assert.equal(calls, 0);
    assert.equal(report.result, "NOT_RUN");
    assert.equal(report.failure.code, "BROWSER_STARTUP_TIMEOUT");
    assert.equal(report.failure.stage, "websocket");
    assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
    assert.equal(JSON.stringify(report).includes(directory), false);
  } finally { await rm(directory, {recursive:true, force:true}); }
});
