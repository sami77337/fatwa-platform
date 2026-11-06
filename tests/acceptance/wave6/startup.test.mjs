// Offline negatives against the Wave6 entry point, not acceptance.
// Run: node --experimental-vm-modules --test tests/acceptance/wave6/startup.test.mjs
import assert from "node:assert/strict";
import {EventEmitter} from "node:events";
import {readFile} from "node:fs/promises";
import path from "node:path";
import {test} from "node:test";
import {fileURLToPath} from "node:url";
import {createContext, SourceTextModule, SyntheticModule} from "node:vm";

// These are the only real file reads. No source rewriting or extracted copy of
// the polling loop: evaluate the actual entry point and both actual imports.
const sources = new Map(await Promise.all(
  ["browser.mjs", "cdp.mjs", "review_batches.mjs"].map(async name => {
    const url = new URL(name, import.meta.url);
    return [url.href, await readFile(url, "utf8")];
  }),
));
const origin = "http://127.0.0.1:43210";
const fixtureBytes = Buffer.from("synthetic asset bytes; NOT browser evidence");

async function simulate({portRead, exitCode = null, signalCode = null,
  spawnError = false, namespace = "wave6-e6-synthetic", headingCount = 47,
  assetFailure, stderr = "", cleanupError, exitDuringRead = false} = {}) {
  let now = 0;
  const state = {polls: [], spawns: [], kills: 0, removals: [], http: [], logs: [], profiles: 0};
  const temporaryRoot = path.resolve("synthetic-e6-no-disk");
  const profile = path.join(temporaryRoot, "fatwa-e6-browser-fixture");
  const artifacts = path.join(temporaryRoot, "reports");
  const browser = new EventEmitter();
  Object.assign(browser, {pid: 123, exitCode, signalCode, stderr: new EventEmitter()});
  browser.kill = () => {
    state.kills++;
    state.cleanupAt = now;
    browser.signalCode = "SIGTERM";
    queueMicrotask(() => browser.emit("exit", null, "SIGTERM"));
  };
  const processFixture = {
    argv: ["node", "browser.mjs", origin],
    env: {E6_BROWSER: "synthetic-no-executable", E6_ARTIFACTS: artifacts, E6_REVIEW_BATCHES: "required"},
    versions: process.versions, version: process.version,
  };
  const builtins = {
    "node:assert/strict": {default: assert},
    "node:path": {default: path},
    "node:url": {fileURLToPath},
    "node:os": {default: {
      tmpdir: () => temporaryRoot, platform: () => "synthetic", release: () => "fixture", arch: () => "fixture",
    }},
    "node:child_process": {
      execFileSync(executable, args) {
        if (executable === "git" && args.join(" ") === "rev-parse HEAD") return "synthetic-not-acceptance";
        if (executable === "git" && args.join(" ") === "status --porcelain") return "";
        assert.equal(executable, "synthetic-no-executable");
        assert.deepEqual(Array.from(args), ["--version"]);
        return "synthetic browser; never executed";
      },
      spawn(executable, args, options) {
        state.spawns.push({executable, args: Array.from(args), options});
        queueMicrotask(() => {
          if (spawnError) browser.emit("error", Object.assign(Error("synthetic spawn unavailable"), {code: "ENOENT"}));
          else browser.emit("spawn");
          browser.stderr.emit("data", stderr.replaceAll("<profile>", profile));
        });
        return browser;
      },
    },
    "node:fs/promises": {
      async mkdir(target) { assert.equal(target, artifacts); },
      async mkdtemp(prefix) {
        assert.equal(prefix, path.join(temporaryRoot, "fatwa-e6-browser-"));
        state.profiles++;
        return profile;
      },
      async readFile(target, encoding) {
        if (target === path.join(profile, "DevToolsActivePort")) {
          assert.equal(encoding, "utf8");
          state.polls.push(now);
          if (exitDuringRead && now === 100) {
            browser.exitCode = 23;
            browser.emit("exit", 23, null);
            browser.emit("close", 23, null);
          }
          if (portRead) return portRead(now);
          throw Object.assign(Error("synthetic missing port file"), {code: "ENOENT"});
        }
        assert.ok(["catalog.js", "django-api.mjs", "tree.js", "style.css", "catalog.css"].some(
          name => target.endsWith(path.join("apps", "reference", "static", "reference", name)),
        ), "Unexpected filesystem read");
        return fixtureBytes;
      },
      async writeFile(target, content) {
        assert.equal(target, path.join(artifacts, "browser-result.json"));
        assert.equal(state.report, undefined, "Only one final report is permitted");
        state.report = JSON.parse(content); // Never write synthetic evidence to disk.
      },
      async rm(target, options) {
        assert.equal(target, profile);
        state.removals.push({target, options});
        if (cleanupError) throw Object.assign(Error("redact-me: " + profile), {code: cleanupError});
      },
    },
  };
  const context = createContext({
    process: processFixture, Buffer, URL, performance: {now: () => now},
    Date: class extends Date {
      constructor(...args) { super(...(args.length ? args : [now])); }
      static now() { return now; }
    },
    // Virtual time only. Cap callbacks so a removed deadline cannot hang a test.
    setTimeout(callback, ms) {
      assert.ok([50, 3000].includes(ms), "Unexpected timer outside startup polling/cleanup");
      assert.ok(now < 20000, "Startup exceeded the deterministic fixture budget");
      now += ms;
      callback();
    },
    AbortSignal: {timeout: () => undefined},
    console: {log: value => state.logs.push(value)},
    async fetch(url) {
      state.http.push(url);
      if (url === origin + "/api/v1/fiqh/books") return {
        json: async () => ({items: [{work: {source_namespace: namespace}, heading_count: headingCount}]}),
      };
      if (url.startsWith(origin + "/assets/reference/")) return {
        status: assetFailure === "status" ? 404 : 200,
        headers: {get: () => assetFailure === "mime" ? "text/html" : url.endsWith(".css") ? "text/css" : "text/javascript"},
        arrayBuffer: async () => assetFailure === "bytes" ? Buffer.from("wrong bytes") : fixtureBytes,
      };
      assert.equal(url, "http://127.0.0.1:9222/json/list", "Unexpected network request");
      state.discoveryAt = now;
      throw Error("synthetic target discovery blocked"); // Never connect, even on loopback.
    },
    WebSocket: class { constructor() { throw Error("Offline fixture forbids WebSocket construction"); } },
  });
  const modules = new Map();
  function moduleAt(identifier) {
    if (!modules.has(identifier)) {
      if (Object.hasOwn(builtins, identifier)) {
        const values = builtins[identifier];
        modules.set(identifier, new SyntheticModule(Object.keys(values), function () {
          for (const [key, value] of Object.entries(values)) this.setExport(key, value);
        }, {context, identifier}));
      } else {
        assert.ok(sources.has(identifier), "Unexpected import: " + identifier);
        modules.set(identifier, new SourceTextModule(sources.get(identifier), {
          context, identifier, initializeImportMeta(meta) { meta.url = identifier; },
        }));
      }
    }
    return modules.get(identifier);
  }
  const entry = moduleAt(new URL("browser.mjs", import.meta.url).href);
  await entry.link((specifier, parent) => moduleAt(
    specifier.startsWith(".") ? new URL(specifier, parent.identifier).href : specifier,
  ));
  await entry.evaluate({timeout: 1000});
  state.exitCode = processFixture.exitCode;
  return state;
}

function assertNoAcceptance(state, result = "BLOCKED") {
  const report = state.report;
  assert.equal(report.result, result);
  assert.equal(report.phase, result === "BLOCKED" ? "browser-startup" : "service-preflight");
  assert.equal(state.exitCode, result === "BLOCKED" ? 2 : 1);
  assert.deepEqual(report.counts, {PASS: 0, FAIL: 0, NOT_RUN: 10, SKIP: 0});
  assert.ok(report.tests.every(item => item.result === "NOT_RUN"));
  for (const key of ["source_acceptance", "assembled_acceptance", "review_batch_acceptance"]) {
    assert.equal(report[key], "NOT_RUN");
  }
  for (const key of ["requests", "screenshots", "console_errors", "exceptions", "unwanted_requests"]) {
    assert.deepEqual(report[key], []);
  }
  assert.equal(report.browser, undefined);
  assert.equal(state.profiles, 1);
  assert.equal(state.removals.length, 1);
  assert.equal(state.spawns.length, result === "BLOCKED" ? 1 : 0);
  if (state.spawns.length) {
    const {executable, args} = state.spawns[0];
    assert.equal(executable, "synthetic-no-executable");
    assert.ok(args.includes("--remote-debugging-address=127.0.0.1"));
    assert.ok(args.includes("--remote-debugging-port=0"));
    assert.ok(args.includes("--user-data-dir=" + state.removals[0].target));
    assert.ok(!args.some(arg => /no-sandbox|disable-setuid-sandbox|disable-web-security/.test(arg)));
  }
}

for (const code of ["ENOENT", "EACCES", "EISDIR"]) {
  test(`${code}: port read failure remains BLOCKED after exactly 12 virtual seconds`, async () => {
    const state = await simulate({portRead() { throw Object.assign(Error("synthetic " + code), {code}); }});
    assertNoAcceptance(state);
    assert.equal(state.report.blocker, "Timed out: DevTools launch");
    assert.equal(state.polls.length, 240);
    assert.equal(state.polls[0], 0);
    assert.equal(state.polls.at(-1), 11950);
    assert.equal(state.cleanupAt, 12000);
    assert.equal(state.kills, 1);
    assert.equal(state.discoveryAt, undefined);
  });
}

for (const content of ["", "not-a-port\n", "0\n"]) {
  test(`non-ready port record ${JSON.stringify(content)} cannot become acceptance`, async () => {
    const state = await simulate({portRead: () => content});
    assertNoAcceptance(state);
    assert.equal(state.report.blocker, "Timed out: DevTools launch");
    assert.equal(state.discoveryAt, undefined);
  });
}

test("the last pre-deadline poll can observe a port without implying browser acceptance", async () => {
  const state = await simulate({portRead: now => now < 11950 ? "" : "9222\n/devtools/browser/synthetic\n"});
  assertNoAcceptance(state);
  assert.equal(state.discoveryAt, 11950);
  assert.equal(state.report.blocker, "synthetic target discovery blocked");
});

test("a port available only at the 12-second boundary is not observed or retried", async () => {
  const state = await simulate({portRead: now => now < 12000 ? "" : "9222\n/devtools/browser/synthetic\n"});
  assertNoAcceptance(state);
  assert.equal(state.report.blocker, "Timed out: DevTools launch");
  assert.equal(state.polls.at(-1), 11950);
  assert.equal(state.discoveryAt, undefined);
});

for (const termination of [{exitCode: 23}, {signalCode: "SIGTERM"}]) {
  test(`early termination ${JSON.stringify(termination)} fails before polling`, async () => {
    const state = await simulate(termination);
    assertNoAcceptance(state);
    assert.equal(state.report.blocker, "Browser exited before DevTools: sandbox/startup gate blocked");
    assert.deepEqual(state.polls, []);
    assert.equal(state.kills, 0);
  });
}

test("spawn error is retained instead of mislabeled as DevTools timeout", async () => {
  const state = await simulate({spawnError: true});
  assertNoAcceptance(state);
  assert.equal(state.report.blocker, "synthetic spawn unavailable");
  assert.ok(state.cleanupAt < 12000);
});

test("startup stderr is bounded and the private profile path is redacted", async () => {
  const state = await simulate({stderr: "x".repeat(5000) + "\nsynthetic D-Bus error at <profile>"});
  assertNoAcceptance(state);
  assert.equal(state.report.blocker, "Timed out: DevTools launch");
  assert.equal(state.report.browser_stderr.length, 2000);
  assert.ok(state.report.browser_stderr.endsWith("synthetic D-Bus error at <temporary-profile>"));
  assert.ok(!state.report.browser_stderr.includes(state.removals[0].target));
});

for (const fixture of [{namespace: "foreign-synthetic"}, {headingCount: 46},
  {assetFailure: "status"}, {assetFailure: "mime"}, {assetFailure: "bytes"}]) {
  test(`preflight mismatch ${JSON.stringify(fixture)} fails before spawn`, async () => {
    const state = await simulate(fixture);
    assertNoAcceptance(state, "FAIL");
    assert.deepEqual(state.polls, []);
    assert.equal(state.kills, 0);
  });
}

test("startup evidence separates missing, unreadable, partial and invalid port records", async () => {
  const state = await simulate({portRead(now) {
    if (now === 0) throw Object.assign(Error("redact-me"), {code: "ENOENT"});
    if (now === 50) throw Object.assign(Error("redact-me"), {code: "EACCES"});
    if (now === 100) return "";
    if (now === 150) return "-2";
    if (now === 200) return "65536";
    if (now === 250) return "9e3";
    return "9222\n/devtools/browser/redact-me\n";
  }});
  assertNoAcceptance(state);
  assert.equal(state.discoveryAt, 300);
  const d = state.report.startup;
  assert.equal(d.stage, "target-discovery");
  assert.equal(d.elapsed_ms, 300);
  assert.equal(d.child.pid, 123);
  assert.equal(d.child.exit_code, null);
  assert.equal(d.child.signal, null); // Sampled before fixture cleanup sends SIGTERM.
  assert.equal(d.spawned_ms, 0);
  assert.deepEqual(d.port_file, {
    attempts: 7, last_state: "valid", last_error_code: "EACCES",
    first_seen_ms: {missing: 0, read_error: 50, empty: 100, invalid: 150, valid: 300},
  });
  assert.ok(!JSON.stringify(d).includes("redact-me"));
});

test("startup evidence distinguishes a signal, a spawn error and a port timeout", async () => {
  const signalled = await simulate({signalCode: "SIGKILL"});
  assertNoAcceptance(signalled);
  assert.equal(signalled.report.startup.child.signal, "SIGKILL");
  const failed = await simulate({spawnError: true});
  assertNoAcceptance(failed);
  assert.equal(failed.report.startup.spawn_error.code, "ENOENT");
  const timed = await simulate();
  assertNoAcceptance(timed);
  const d = timed.report.startup;
  assert.equal(d.stage, "port-file");
  assert.equal(d.elapsed_ms, 12000);
  assert.equal(d.port_file.attempts, 240);
  assert.deepEqual(d.port_file.first_seen_ms, {missing: 0});
  assert.equal(d.port_file.last_error_code, "ENOENT");
});

test("early process exit records monotonic lifecycle and keeps journeys unexecuted", async () => {
  const state = await simulate({exitDuringRead: true});
  assertNoAcceptance(state);
  assert.equal(state.report.startup.exit_ms, 100);
  assert.equal(state.report.startup.close_ms, 100);
  assert.equal(state.report.startup.child.exit_code, 23);
  assert.equal(state.report.startup.elapsed_ms, 150);
});

test("profile-removal failure preserves the startup report and fails the gate", async () => {
  const state = await simulate({cleanupError: "EACCES"});
  assert.equal(state.exitCode, 1);
  assert.equal(state.report.result, "FAIL");
  assert.equal(state.report.result_before_cleanup, "BLOCKED");
  assert.equal(state.report.cleanup_error, "EACCES");
  assert.equal(state.report.startup.port_file.last_state, "missing");
  assert.deepEqual(state.report.counts, {PASS: 0, FAIL: 0, NOT_RUN: 10, SKIP: 0});
  assert.ok(!JSON.stringify(state.report).includes("redact-me"));
});
