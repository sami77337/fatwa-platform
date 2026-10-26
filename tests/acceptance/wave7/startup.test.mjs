// Diagnostic doubles only: these tests never claim browser/PG acceptance.
import assert from "node:assert/strict";
import {execFile} from "node:child_process";
import {access, mkdir, mkdtemp, readFile, rm, writeFile} from "node:fs/promises";
import {createServer} from "node:http";
import os from "node:os";
import path from "node:path";
import {test} from "node:test";
import {fileURLToPath} from "node:url";
import {promisify} from "node:util";
import {ProtectedBrowser, recordBrowserFailure, closeBrowser} from "./startup.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const route = "/dev/editorial-preview/persisted";
const scenario = {worklist_path:route, batch_ids:["synthetic-a", "synthetic-b"],
  detail_paths:[route, route], blocked_detail_path:route, reviewed_detail_path:route,
  missing_media_detail_path:route, invalid_media_detail_path:route, unresolved_detail_path:route};

for (const [script, filename, count] of [
  ["browser.mjs", "browser-result.json", 4],
  ["persisted_browser.mjs", "workflow-result.json", 8],
]) {
  for (const invalidAsset of [false, true]) test(`${script}: ${invalidAsset ? "asset failure stays FAIL" : "spawn failure stays BLOCKED with diagnostics and cleanup"}`, async () => {
    const folder = await mkdtemp(path.join(os.tmpdir(), "wave7-launch-regression-"));
    const server = createServer(async (request, response) => {
      try {
        if (request.url.startsWith("/api/v1/fiqh/books")) {
          response.setHeader("Content-Type", "application/json");
          response.end(JSON.stringify({items:[{work:{source_namespace:"wave7-synthetic-toc"}, heading_count:3}]}));
        } else if (request.url.startsWith(route)) response.end('<main id="wave7-persisted"></main>');
        else {
          const name = path.posix.basename(request.url);
          const file = request.url === "/dev/editorial-preview/style.css"
            ? "apps/editorial_demo/preview.css" : "apps/reference/static/reference/" + name;
          response.setHeader("Content-Type", name.endsWith(".css") ? "text/css" : "text/javascript");
          response.end(invalidAsset ? "invalid asset bytes" : await readFile(path.join(root, file)));
        }
      } catch { response.writeHead(500).end(); }
    });
    try {
      await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
      const manifest = path.join(folder, "scenario.json");
      await writeFile(manifest, JSON.stringify(scenario));
      const artifacts = path.join(folder, "artifacts");
      await mkdir(artifacts);
      const args = [path.join(root, "tests/acceptance/wave7", script), `http://127.0.0.1:${server.address().port}`, manifest];
      await assert.rejects(promisify(execFile)(process.execPath, args, {cwd:root, timeout:15000,
        env:{...process.env, E6_BROWSER:path.join(folder, "missing-browser"),
          E6_PYTHON:process.env.FATWA_FASTBUILD_PYTHON ?? (process.platform === "win32" ? "python" : "python3"),
          E6_WAVE7_ARTIFACTS:artifacts}, windowsHide:true}), {code:invalidAsset ? 1 : 2});
      const report = JSON.parse(await readFile(path.join(artifacts, filename), "utf8"));
      assert.equal(report.result, invalidAsset ? "FAIL" : "BLOCKED");
      assert.equal(report.phase, invalidAsset ? "service-preflight" : "browser-startup");
      assert.deepEqual(report.counts, {PASS:0, FAIL:0, NOT_RUN:count, SKIP:0});
      assert.deepEqual(report.requests, []);
      assert.equal(report.source_acceptance, "NOT_RUN");
      if (invalidAsset) assert.equal(report.startup, undefined, "preflight failures must not launch a browser");
      else {
        assert.deepEqual(report.failure, {code:"BROWSER_SPAWN_FAILED", stage:"port-file", cause_code:"ENOENT"});
        assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
        assert.equal(report.startup.timeout_ms, 30000);
        assert.equal(report.startup.stage, "port-file");
        assert.equal(typeof report.startup.elapsed_ms, "number");
      }
    } finally {
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
      assert.equal(path.dirname(path.resolve(folder)), path.resolve(os.tmpdir()));
      assert.ok(path.basename(folder).startsWith("wave7-launch-regression-"));
      await rm(folder, {recursive:true, force:true});
    }
  });
}

test("protected startup accepts a port arriving after Wave7's former 12 second deadline", async () => {
  const browser = new ProtectedBrowser({executable:process.execPath,
    args:[fileURLToPath(new URL("./startup_fixture.mjs", import.meta.url)), "delayed-port"]});
  const report = {result:"NOT_RUN"};
  try {
    assert.equal((await browser.start()).readyState, WebSocket.OPEN);
    assert.ok(browser.elapsedMs >= 12500);
    const flags = JSON.parse(await readFile(path.join(browser.profile, "launch.json"), "utf8"));
    for (const flag of ["--disable-background-networking", "--disable-component-update", "--disable-sync",
      "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"]) assert.ok(flags.includes(flag));
    assert.ok(!flags.some(flag => /no-sandbox|disable-setuid-sandbox|disable-web-security|disable-features/.test(flag)));
  } finally { await closeBrowser(report, browser); }
  assert.equal(report.startup.timeout_ms, 30000);
  assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
  assert.equal(report.result, "NOT_RUN", "lifecycle success alone is not acceptance");
  await assert.rejects(access(browser.profile), {code:"ENOENT"});
  assert.deepEqual(await browser.close(), report.cleanup, "cleanup is idempotent");
});

for (const [mode, code, stage] of [
  ["missing-port", "BROWSER_STARTUP_TIMEOUT", "port-file"],
  ["http-hang", "BROWSER_STARTUP_TIMEOUT", "target-discovery"],
  ["socket-hang", "BROWSER_STARTUP_TIMEOUT", "websocket"],
  ["foreign-socket", "DEVTOOLS_ENDPOINT_INVALID", "target-discovery"],
]) test(`${mode}: bounded startup preserves BLOCKED and stage diagnostics`, async () => {
  const browser = new ProtectedBrowser({executable:process.execPath,
    args:[fileURLToPath(new URL("./startup_fixture.mjs", import.meta.url)), mode], startupTimeoutMs:1500});
  const report = {result:"NOT_RUN"};
  try {
    await assert.rejects(browser.start(), error => {
      recordBrowserFailure(report, error, "browser-startup");
      return error.code === code && error.stage === stage;
    });
  } finally { await closeBrowser(report, browser); }
  assert.equal(report.result, "BLOCKED");
  assert.equal(report.failure.code, code);
  assert.equal(report.failure.stage, stage);
  assert.deepEqual(report.cleanup, {result:"PASS", errors:[]});
  await assert.rejects(access(browser.profile), {code:"ENOENT"});
});

test("cleanup cannot promote BLOCKED/FAIL and cleanup errors invalidate successful cases", async () => {
  for (const phase of ["service-preflight", "browser-startup", "interactions"]) {
    const report = {};
    recordBrowserFailure(report, Error("original failure"), phase);
    await closeBrowser(report, {close:async () => ({result:"PASS", errors:[]}), stderr:""});
    assert.equal(report.result, phase === "browser-startup" ? "BLOCKED" : "FAIL");
    assert.equal(report.blocker, "original failure");
  }
  for (const result of ["PASS", "PASS_BASELINE_ONLY", "BLOCKED", "FAIL"]) {
    const report = {result};
    await closeBrowser(report, {close:async () => ({result:"FAIL", errors:["TREE_CLEANUP_TIMEOUT"]}),
      profile:"/synthetic/profile", stderr:"/synthetic/profile diagnostic"});
    assert.equal(report.result, "FAIL");
    assert.equal(report.browser_stderr, "<temporary-profile> diagnostic");
  }
});
