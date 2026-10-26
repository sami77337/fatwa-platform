import assert from "node:assert/strict";
import {execFile, spawn} from "node:child_process";
import {once} from "node:events";
import {access, mkdtemp, open, readFile, rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {setTimeout as delay} from "node:timers/promises";
import {fileURLToPath} from "node:url";
import {mock, test} from "node:test";
import {ProtectedBrowser} from "../acceptance/fastbuild/startup.mjs";
import {runResearchBrowser} from "./startup.mjs";

const script = fileURLToPath(new URL("./browser.mjs", import.meta.url));
const fixture = fileURLToPath(new URL("./startup_fixture.mjs", import.meta.url));

async function running(pid, read = readFile) {
  if (process.platform === "linux") {
    try { return (await read(`/proc/${pid}/stat`, "utf8")).split(") ")[1][0] !== "Z"; }
    catch (error) { if (error.code === "ENOENT" || error.code === "ESRCH") return false; throw error; }
  }
  try { process.kill(pid, 0); return true; }
  catch (error) { if (error.code === "ESRCH") return false; throw error; }
}

test("research Linux liveness handles an open proc handle reaped before read", {skip:process.platform !== "linux"}, async () => {
  const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {stdio:"ignore"});
  const closed = once(child, "close");
  let stat;
  try {
    await once(child, "spawn");
    assert.equal(await running(child.pid), true);
    stat = await open(`/proc/${child.pid}/stat`, "r");
    child.kill("SIGKILL");
    await closed;
    await assert.rejects(stat.readFile("utf8"), {code:"ESRCH"});
    assert.equal(await running(child.pid, () => stat.readFile("utf8")), false);
    assert.equal(await running(child.pid), false);
    assert.equal(await running(123, async () => "123 (synthetic) Z 1 2 3"), false);
    for (const code of ["EACCES", "EPERM", "EIO"]) {
      const error = Object.assign(Error("proc read failed"), {code});
      await assert.rejects(running(123, async () => { throw error; }), actual => actual === error);
    }
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    await closed;
    await stat?.close();
  }
});

async function withFixture(mode, interact, options = {}) {
  const temp = await mkdtemp(path.join(os.tmpdir(), "fatwa-research-startup-test-"));
  try {
    const record = path.join(temp, "launch.json");
    const report = await runResearchBrowser(interact, {
      executable:process.execPath, args:[fixture, mode, record], startupTimeoutMs:2000, ...options,
    });
    const launch = JSON.parse(await readFile(record, "utf8"));
    await assert.rejects(access(launch.profile), {code:"ENOENT"});
    for (const pid of [launch.pid, launch.child].filter(Boolean)) {
      const deadline = performance.now() + 2000;
      while (await running(pid) && performance.now() < deadline) await delay(20);
      assert.equal(await running(pid), false, "owned browser/descendant survived cleanup");
    }
    return {report, launch};
  } finally {
    assert.equal(path.dirname(path.resolve(temp)), path.resolve(os.tmpdir()));
    assert.ok(path.basename(temp).startsWith("fatwa-research-startup-test-"));
    await rm(temp, {recursive:true, force:true});
  }
}

test("legacy entrypoint reports missing Chrome as NOT_RUN with successful cleanup", async () => {
  const result = await new Promise(resolve => execFile(process.execPath, [script, "http://127.0.0.1:9"], {
    env:{...process.env, FATWA_FASTBUILD_BROWSER:script + ".missing"}, timeout:12000,
  }, (error, stdout, stderr) => resolve({error, stdout, stderr})));
  const report = JSON.parse(result.stdout.trim() || "{}");
  assert.equal(report.result, "NOT_RUN", result.stderr);
  assert.equal(result.error?.code, 2);
  assert.equal(report.failure.code, "BROWSER_SPAWN_FAILED");
  assert.equal(report.failure.stage, "port-file");
  assert.equal(report.failure.cause_code, "ENOENT");
  assert.equal(report.cleanup.result, "PASS");
  assert.equal(result.stderr, "");
});

test("port readiness after ten seconds runs the journey once with protected flags", async () => {
  let calls = 0;
  const {report, launch} = await withFixture("slow-port", async socket => {
    calls++;
    assert.equal(socket.readyState, WebSocket.OPEN);
    return {checks:["synthetic lifecycle only"]};
  }, {startupTimeoutMs:20000});
  assert.equal(calls, 1);
  assert.equal(report.result, "PASS");
  assert.equal(report.cleanup.result, "PASS");
  assert.ok(report.startup.elapsed_ms >= 11000);
  assert.ok(report.startup.elapsed_ms < 20000);
  assert.ok(launch.args.includes("--remote-debugging-address=127.0.0.1"));
  assert.ok(launch.args.includes("--disable-background-networking"));
  assert.equal(launch.args.some(arg => /no-sandbox|disable.*sandbox|disable-web-security|ignore-certificate-errors/.test(arg)), false);
});

for (const [mode, code, stage] of [
  ["stderr-exit", "BROWSER_EXITED", "port-file"],
  ["missing-port-tree", "BROWSER_STARTUP_TIMEOUT", "port-file"],
  ["invalid-port", "DEVTOOLS_PORT_INVALID", "port-file"],
  ["http-hang", "BROWSER_STARTUP_TIMEOUT", "target-discovery"],
  ["foreign-socket", "DEVTOOLS_ENDPOINT_INVALID", "target-discovery"],
  ["socket-hang", "BROWSER_STARTUP_TIMEOUT", "websocket"],
]) test(`${mode} is classified without running assertions and cleans its tree/profile`, async () => {
  let calls = 0;
  const start = performance.now();
  const {report, launch} = await withFixture(mode, () => { calls++; });
  assert.equal(calls, 0);
  assert.equal(report.result, "NOT_RUN");
  assert.equal(report.failure.code, code);
  assert.equal(report.failure.stage, stage);
  assert.equal(report.cleanup.result, "PASS");
  assert.ok(performance.now() - start < 10000, "failure and cleanup must remain bounded");
  if (mode === "stderr-exit") {
    assert.equal(report.failure.cause_code, 23);
    assert.deepEqual(report.diagnostics, {stderr_present:true, stderr_hints:["SANDBOX_UNAVAILABLE"]});
    const encoded = JSON.stringify(report);
    for (const privateText of [launch.profile, "private-value", "secret", "example.invalid"])
      assert.equal(encoded.includes(privateText), false);
  }
});

test("an original journey assertion failure stays FAIL after successful cleanup", async () => {
  const {report} = await withFixture("delayed-target", () => assert.fail("private assertion detail"));
  assert.equal(report.result, "FAIL");
  assert.equal(report.failure.code, "ERR_ASSERTION");
  assert.equal(report.failure.stage, "interactions");
  assert.equal(report.cleanup.result, "PASS");
  assert.equal(JSON.stringify(report).includes("private assertion detail"), false);
});

test("the run watchdog interrupts a stalled journey and cleans up", async () => {
  let calls = 0;
  const {report} = await withFixture("delayed-target", () => {
    calls++;
    return new Promise(() => {});
  }, {runTimeoutMs:2000});
  assert.equal(calls, 1);
  assert.equal(report.result, "FAIL");
  assert.equal(report.failure.code, "RUN_DEADLINE_EXCEEDED");
  assert.equal(report.cleanup.result, "PASS");
});

test("cleanup failure overrides successful journey assertions", async () => {
  const close = ProtectedBrowser.prototype.close;
  const stub = mock.method(ProtectedBrowser.prototype, "close", async function () {
    await close.call(this); // Keep real containment and deletion, inject only the failure result.
    return {result:"FAIL", errors:["TREE_CLEANUP_TIMEOUT"]};
  });
  try {
    const {report} = await withFixture("delayed-target", () => ({checks:["synthetic"]}));
    assert.equal(report.result, "FAIL");
    assert.deepEqual(report.cleanup.errors, ["TREE_CLEANUP_TIMEOUT"]);
  } finally { stub.mock.restore(); }
});
