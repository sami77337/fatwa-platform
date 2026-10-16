import test from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { randomUUID } from "node:crypto";
import {
  workspace, siteName, databaseName, networkName, actions, parseArguments, childEnvironment,
  dockerEndpoint, validateSite, makeDocker, inspectSite, operate, OperationError,
  acquireLock, writeReport, unitTests,
} from "../../tools/dev/local.mjs";

const execute = promisify(execFile);
function fixture() {
  const site = {
    Name: "/" + siteName, State: { Running: true },
    Config: { Env: ["PGHOST=postgres", "PGPORT=5432", "PGDATABASE=fatwa_reference", "PGUSER=fatwa_app",
      "DJANGO_SETTINGS_MODULE=config.settings.development"],
      Entrypoint: ["sh", "-c"], Cmd: ["python manage.py runserver 0.0.0.0:8000 --noreload"] },
    HostConfig: { Privileged: false, NetworkMode: "bridge", PublishAllPorts: false,
      PortBindings: { "8000/tcp": [{ HostIp: "127.0.0.1", HostPort: "8000" }] } },
    NetworkSettings: { Networks: { bridge: {}, [networkName]: {} } },
    Mounts: [
      { Type: "bind", Source: workspace, Destination: "/app", RW: false },
      { Type: "bind", Source: "C:/synthetic owner/secret-file", Destination: "/run/secrets/app-password", RW: false },
    ],
  };
  const database = {
    Name: "/" + databaseName, State: { Running: true, Health: { Status: "healthy" } },
    Config: { Image: "postgres:18.6-bookworm", Labels: {
      "com.docker.compose.project": "fatwa-s5-dev-pg18", "com.docker.compose.service": "postgres",
    } },
    HostConfig: { Privileged: false, NetworkMode: networkName,
      PortBindings: { "5432/tcp": [{ HostIp: "127.0.0.1", HostPort: "55432" }] } },
    NetworkSettings: { Networks: { [networkName]: { Aliases: ["postgres"], IPAddress: "172.25.0.2" } } },
  };
  return { site, database, network: { Name: networkName, Internal: true, Driver: "bridge" } };
}
const healthy = async () => ({ result: "PASS", http_behavior: "PASS" });

test("arguments are an exact single-action allowlist with no port, source or container overrides", () => {
  assert.equal(parseArguments([]), "start");
  for (const action of [...actions, "--help"]) assert.equal(parseArguments([action]), action);
  for (const args of [["START"], ["--port=9000"], ["start", "restart"], ["import"], ["migrate"],
    ["--container=other"], ["start & echo injected"], ["https://remote.invalid"]]) {
    assert.throws(() => parseArguments(args), error => error.code === "INVALID_ARGUMENTS");
  }
});
test("local Docker endpoints reject remote transports and malformed named pipes", () => {
  for (const endpoint of ["npipe:////./pipe/docker_engine", "unix:///var/run/docker.sock"]) {
    assert.equal(dockerEndpoint(endpoint), endpoint);
  }
  for (const endpoint of ["tcp://127.0.0.1:2375", "ssh://remote", "npipe:////remote/pipe/docker",
    "npipe:////./pipe/foo\nbad", "npipe:////./pipe/foo/remote", "https://remote.invalid"]) {
    assert.throws(() => dockerEndpoint(endpoint));
  }
});
test("inherited database, secret and Node hook environment is removed without mutating the owner environment", () => {
  const input = { PATH: "runtime", SystemRoot: "system", PGPASSWORD: "synthetic", pgservice: "wrong",
    DATABASE_URL: "synthetic", DJANGO_SETTINGS_MODULE: "production", FATWA_PRODUCTION: "1",
    DOCKER_HOST: "tcp://remote", docker_context: "remote", NODE_OPTIONS: "--require bad",
    OPENAI_API_KEY: "synthetic", ACCESS_TOKEN: "synthetic", NODE_USE_ENV_PROXY: "1" };
  const output = childEnvironment(input);
  assert.deepEqual(output, { PATH: "runtime", SystemRoot: "system" });
  assert.equal(input.PGPASSWORD, "synthetic");
});
test("topology supports spaces and Docker Desktop path mapping only for this read-only copy", () => {
  const original = fixture();
  assert.deepEqual(validateSite(original.site, original.database, original.network), {
    site_running: true, database_running: true, database_healthy: true,
  });
  const target = "C:/Users/Owner ! & [home]/A6 site";
  original.site.Mounts[0].Source = "/run/desktop/mnt/host/c/Users/Owner ! & [home]/A6 site";
  assert.doesNotThrow(() => validateSite(original.site, original.database, original.network, target));
});
test("topology refuses original/sibling copies, write mounts, extra ports, extra networks and maintenance commands", () => {
  const changes = [
    f => { f.site.Name = "/unrelated"; },
    f => { f.database.Name = "/unrelated"; },
    f => { f.network.Internal = false; },
    f => { f.network.Driver = "overlay"; },
    f => { f.database.Config.Image = "postgres:17"; },
    f => { f.database.HostConfig.PortBindings["5432/tcp"][0].HostIp = "0.0.0.0"; },
    f => { f.database.HostConfig.PortBindings["5432/tcp"][0].HostPort = "5432"; },
    f => { f.database.NetworkSettings.Networks.bridge = {}; },
    f => { f.site.HostConfig.Privileged = true; },
    f => { f.site.HostConfig.NetworkMode = "host"; },
    f => { f.site.HostConfig.NetworkMode = "container:other"; },
    f => { f.site.HostConfig.PublishAllPorts = true; },
    f => { f.site.HostConfig.PortBindings["8000/tcp"][0].HostIp = "0.0.0.0"; },
    f => { f.site.HostConfig.PortBindings["9000/tcp"] = [{ HostIp: "127.0.0.1", HostPort: "9000" }]; },
    f => { f.site.NetworkSettings.Networks.external = {}; },
    f => { f.site.Mounts[0].Source = "C:/integration/site-v1"; },
    f => { f.site.Mounts[0].RW = true; },
    f => { f.site.Mounts[1].RW = true; },
    f => { f.site.Mounts.push({ Type: "bind", Source: "/var/run/docker.sock", Destination: "/var/run/docker.sock", RW: false }); },
    f => { f.site.Config.Env.push("PGPASSWORD=synthetic-do-not-print"); },
    f => { f.site.Config.Env.push("PGUSER=fatwa_bootstrap"); },
    f => { f.site.Config.Env[2] = "PGDATABASE=other"; },
    f => { f.site.Config.Env[0] = "PGHOST=remote.invalid"; },
    f => { f.site.Config.Env.push("FATWA_PRODUCTION=1"); },
    f => { f.site.Config.Cmd = ["python manage.py migrate; python manage.py runserver 0.0.0.0:8000"]; },
    f => { f.site.Config.Cmd = ["python manage.py import_book622; python manage.py runserver 0.0.0.0:8000"]; },
  ];
  for (const mutate of changes) {
    const data = fixture(); mutate(data);
    assert.throws(() => validateSite(data.site, data.database, data.network), OperationError);
  }
});
test("Docker invocations use argument arrays, explicit local endpoint, hidden windows, bounded timeout and no shell", async () => {
  const calls = [];
  const docker = await makeDocker({
    environment: { PATH: "safe", DOCKER_HOST: "npipe:////./pipe/docker_engine", PGPASSWORD: "synthetic" },
    executeFile: async (exe, args, options) => { calls.push({ exe, args, options }); return { stdout: "ok\n" }; },
  });
  await docker(["inspect", "--type", "container", siteName]);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].args, ["--host", "npipe:////./pipe/docker_engine", "inspect", "--type", "container", siteName]);
  assert.equal(calls[0].exe, "docker");
  assert.equal(calls[0].options.cwd, workspace);
  assert.equal(calls[0].options.shell, false);
  assert.equal(calls[0].options.windowsHide, true);
  assert.equal(calls[0].options.timeout, 15000);
  assert.equal(calls[0].options.env.PGPASSWORD, undefined);
});
test("remote Docker is rejected before any process and raw Docker stderr is never reported", async () => {
  let calls = 0;
  await assert.rejects(makeDocker({ environment: { DOCKER_HOST: "tcp://remote:2375" },
    executeFile: async () => { calls++; } }), error => error.code === "REMOTE_DOCKER_REFUSED");
  assert.equal(calls, 0);
  const docker = await makeDocker({ environment: { DOCKER_HOST: "npipe:////./pipe/docker_engine" },
    executeFile: async () => { throw Error("PGPASSWORD=synthetic-do-not-print"); } });
  await assert.rejects(docker(["inspect", siteName]), error =>
    error.code === "DOCKER_UNAVAILABLE" && !error.message.includes("synthetic"));
});
test("Docker current-context endpoint is validated before any daemon operation", async () => {
  const calls = [];
  await assert.rejects(makeDocker({ environment: {},
    executeFile: async (_exe, args) => { calls.push(args); return { stdout: "ssh://remote" }; } }));
  assert.deepEqual(calls, [["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]]);
});
test("inspection queries only the exact named containers/network, without listing other resources", async () => {
  const data = fixture();
  const calls = [];
  const docker = async args => {
    calls.push(args);
    if (args[0] === "version") return "28.5.0";
    return JSON.stringify([args[0] === "network" ? data.network : args.at(-1) === siteName ? data.site : data.database]);
  };
  assert.equal((await inspectSite(docker)).state.site_running, true);
  assert.deepEqual(calls, [
    ["inspect", "--type", "container", siteName], ["inspect", "--type", "container", databaseName],
    ["network", "inspect", networkName], ["version", "--format", "{{.Server.Version}}"],
  ]);
});
function harness(state = { site_running: false, database_running: true, database_healthy: true }) {
  const calls = [];
  const docker = async args => { calls.push(args); };
  const options = {
    getDocker: async () => docker, checkHealth: healthy, inspect: async () => ({ state }),
    waitReady: async () => {}, lock: async () => { calls.push("lock"); return async () => { calls.push("unlock"); }; },
  };
  return { calls, options };
}
test("start touches only the named site and releases its own lock", async () => {
  const { calls, options } = harness();
  const report = await operate("start", options);
  assert.equal(report.result, "PASS");
  assert.equal(report.source_import, "NOT_RUN");
  assert.deepEqual(calls, ["lock", ["start", siteName], "unlock"]);
});
test("start is idempotent for an already-running verified site", async () => {
  const { calls, options } = harness({ site_running: true, database_running: true, database_healthy: true });
  const report = await operate("start", options);
  assert.equal(report.container_action, "ALREADY_RUNNING");
  assert.deepEqual(calls, ["lock", "unlock"]);
});
test("restart targets exactly the site and never its database", async () => {
  const { calls, options } = harness();
  const report = await operate("restart", options);
  assert.equal(report.result, "PASS");
  assert.deepEqual(calls, ["lock", ["restart", "--time", "10", siteName], "unlock"]);
});
test("stopped/unhealthy database blocks lifecycle while independently recording working HTTP", async () => {
  for (const state of [
    { site_running: false, database_running: false, database_healthy: false },
    { site_running: true, database_running: true, database_healthy: false },
  ]) {
    const { calls, options } = harness(state);
    const report = await operate("restart", options);
    assert.equal(report.result, "FAIL");
    assert.equal(report.failure.code, "DATABASE_NOT_READY");
    assert.equal(report.health.result, "PASS");
    assert.deepEqual(calls, ["lock", "unlock"]);
  }
});
test("status and healthcheck cannot acquire a lifecycle lock or mutate Docker", async () => {
  const { calls, options } = harness({ site_running: true, database_running: true, database_healthy: true });
  options.lock = async () => { throw Error("must not lock"); };
  assert.equal((await operate("status", options)).result, "PASS");
  options.getDocker = async () => { throw Error("must not call Docker"); };
  assert.equal((await operate("healthcheck", options)).result, "PASS");
  assert.deepEqual(calls, []);
});
test("Docker failure reports a nonzero outcome with live HTTP evidence and no secret values", async () => {
  const { options, calls } = harness();
  options.getDocker = async () => { throw Error("synthetic-secret"); };
  const report = await operate("start", options);
  assert.equal(report.result, "FAIL");
  assert.equal(report.health.result, "PASS");
  assert.equal(report.failure.code, "LOCAL_OPERATION_FAILED");
  assert.ok(!JSON.stringify(report).includes("synthetic-secret"));
  assert.deepEqual(calls, ["lock", "unlock"]);
});
test("HTTP readiness failure after restart cannot claim lifecycle success", async () => {
  const { options } = harness();
  options.waitReady = async () => { throw new OperationError("SITE_NOT_READY", "Site did not become ready."); };
  const report = await operate("restart", options);
  assert.equal(report.result, "FAIL");
  assert.equal(report.container_action, "RESTARTED_NAMED_SITE");
  assert.equal(report.failure.code, "SITE_NOT_READY");
});
test("failure cannot release a lock owned by another run", async () => {
  const { calls, options } = harness();
  options.lock = async () => { throw new OperationError("RUNNER_LOCKED", "Locked."); };
  assert.equal((await operate("start", options)).failure.code, "RUNNER_LOCKED");
  assert.deepEqual(calls, []);
});
async function scratch() {
  const directory = path.join(workspace, "tests/dev/.local", "A6 path ! & [space] ' " + randomUUID());
  await fs.mkdir(directory, { recursive: true });
  return directory;
}
test("exclusive locks survive competing launch attempts; only the owner releases them", async () => {
  const directory = await scratch();
  try {
    const release = await acquireLock(directory);
    const before = await fs.readFile(path.join(directory, "operation.lock"), "utf8");
    await assert.rejects(acquireLock(directory), error => error.code === "RUNNER_LOCKED");
    assert.equal(await fs.readFile(path.join(directory, "operation.lock"), "utf8"), before);
    await release();
    const again = await acquireLock(directory);
    await again();
  } finally { await fs.rmdir(directory); }
});
test("atomic per-action reports preserve previous host import evidence", async () => {
  const directory = await scratch();
  try {
    await fs.writeFile(path.join(directory, "host-result.json"), "prior-host-evidence");
    await writeReport("healthcheck", { result: "PASS" }, directory);
    await writeReport("healthcheck", { result: "FAIL" }, directory);
    assert.equal(JSON.parse(await fs.readFile(path.join(directory, "a6-healthcheck-result.json"), "utf8")).result, "FAIL");
    assert.equal(await fs.readFile(path.join(directory, "host-result.json"), "utf8"), "prior-host-evidence");
    assert.deepEqual((await fs.readdir(directory)).sort(), ["a6-healthcheck-result.json", "host-result.json"]);
  } finally {
    await fs.unlink(path.join(directory, "a6-healthcheck-result.json"));
    await fs.unlink(path.join(directory, "host-result.json"));
    await fs.rmdir(directory);
  }
});
test("dedicated regression command propagates child failure without leaking child output", async () => {
  const result = await unitTests({ executeFile: async () => { throw Error("synthetic-private-output"); } });
  assert.equal(result.result, "FAIL");
  assert.ok(!JSON.stringify(result).includes("synthetic-private-output"));
});
test("CLI invalid actions exit 2 and help does not access Docker or HTTP", async () => {
  const output = await execute(process.execPath, ["tools/dev/host.mjs", "--help"], { cwd: workspace, windowsHide: true });
  assert.match(output.stdout, /No import/);
  await assert.rejects(execute(process.execPath, ["tools/dev/host.mjs", "--port=9000"], {
    cwd: workspace, windowsHide: true,
  }), error => error.code === 2 && /Use one action/.test(error.stderr));
});
test("database test button is fail-closed with NOT_RUN, no live credentials, and nonzero exit", async () => {
  await assert.rejects(execute(process.execPath, ["tools/dev/host.mjs", "test-db"], {
    cwd: workspace, windowsHide: true, env: { ...process.env, PGPASSWORD: "synthetic-private-password" },
  }), error => error.code === 1 && error.stdout.includes("DATABASE_ISOLATION_NOT_PROVEN") &&
    error.stdout.includes('"django_postgresql_tests": "NOT_RUN"') && !error.stdout.includes("synthetic-private-password"));
});
test("actual Node argument arrays preserve paths with spaces and shell metacharacters", async () => {
  const argument = "C:/Users/Owner ! & ' []/site; $(not-a-command)/manage.py";
  const result = await execute(process.execPath, ["-e", "console.log(JSON.stringify(process.argv.slice(1)))", argument], {
    cwd: workspace, shell: false, windowsHide: true,
  });
  assert.deepEqual(JSON.parse(result.stdout), [argument]);
});
test("actual PowerShell call operator preserves a copied launcher path with spaces and metacharacters", { skip: process.platform !== "win32" }, async t => {
  const directory = await scratch();
  try {
    await fs.copyFile(path.join(workspace, "tools/dev/site.ps1"), path.join(directory, "site.ps1"));
    await fs.writeFile(path.join(directory, "host.mjs"), "console.log(JSON.stringify(process.argv.slice(2)));");
    const result = await execute("powershell.exe", ["-NoProfile", "-NonInteractive", "-File",
      path.join(directory, "site.ps1"), "-Action", "Restart"], { cwd: workspace, shell: false, windowsHide: true });
    assert.deepEqual(JSON.parse(result.stdout), ["restart"]);
  } catch (error) {
    if (/running scripts is disabled/.test(error.stderr ?? "")) t.skip("Host execution policy blocks .ps1 files; no policy was changed. CMD wrappers are tested separately.");
    else throw error;
  } finally {
    await fs.unlink(path.join(directory, "site.ps1"));
    await fs.unlink(path.join(directory, "host.mjs"));
    await fs.rmdir(directory);
  }
});
for (const [file, action] of [
  ["START_LOCAL.cmd", "start"], ["RESTART_LOCAL.cmd", "restart"], ["STATUS_LOCAL.cmd", "status"],
  ["HEALTHCHECK_LOCAL.cmd", "healthcheck"], ["TEST_LOCAL.cmd", "test"], ["TEST_DATABASE.cmd", "test-db"],
]) {
  test("actual " + file + " handles a spaced/metacharacter path and propagates failure", { skip: process.platform !== "win32" }, async () => {
    const directory = await scratch();
    try {
      const target = path.join(directory, file);
      await fs.copyFile(path.join(workspace, "tools/dev", file), target);
      await fs.writeFile(path.join(directory, "host.mjs"),
        "console.log(JSON.stringify(process.argv.slice(2))); process.exitCode=7;");
      const env = { ...process.env, FATWA_NO_PAUSE: "1", FATWA_NO_BROWSER: "1" };
      await assert.rejects(execute("cmd.exe", ["/d", "/s", "/c", '""' + target + '""'], {
        cwd: workspace, env, windowsHide: true, windowsVerbatimArguments: true,
      }), error => error.code === 7 && error.stdout.includes(JSON.stringify([action])));
    } finally {
      await fs.unlink(path.join(directory, file));
      await fs.unlink(path.join(directory, "host.mjs"));
      await fs.rmdir(directory);
    }
  });
}
test("legacy operational entry points contain no source apply or Django test execution", async () => {
  const python = await fs.readFile(path.join(workspace, "tools/dev/container_workflow.py"), "utf8");
  assert.ok(!python.includes("apply=True"));
  assert.ok(!python.includes('call_command("migrate"'));
  assert.ok(!python.includes('"--keepdb"'));
  assert.match(python, /before\["preview"\]\["unchanged"\]/);
  assert.match(python, /Original titles differ/);
  const powershell = await fs.readFile(path.join(workspace, "tools/dev/site.ps1"), "utf8");
  assert.ok(!powershell.includes("PGPASSWORD"));
  assert.ok(!powershell.includes("Set-Content"));
});

test("online install/fetch commands are refused before starting a container", () => {
  for (const command of [
    "pip install -r requirements.txt; python manage.py runserver 0.0.0.0:8000",
    "curl https://external.invalid; python manage.py runserver 0.0.0.0:8000",
  ]) {
    const data = fixture();
    data.site.Config.Cmd = [command];
    assert.throws(() => validateSite(data.site, data.database, data.network),
      error => error.code === "UNSAFE_START_COMMAND");
  }
});
test("Docker missing CLI/object and permission failures receive actionable private diagnostics", async () => {
  for (const [failure, code] of [
    [{ code: "ENOENT" }, "DOCKER_NOT_INSTALLED"],
    [{ stderr: "No such object: synthetic-private-object" }, "EXISTING_OBJECT_MISSING"],
    [{ stderr: "permission denied; synthetic-private-credential" }, "DOCKER_PERMISSION_DENIED"],
  ]) {
    const docker = await makeDocker({ environment: { DOCKER_HOST: "npipe:////./pipe/docker_engine" },
      executeFile: async () => { throw failure; } });
    await assert.rejects(docker(["inspect", siteName]), error =>
      error.code === code && !error.message.includes("synthetic-private"));
  }
});
test("status fails when the database is unhealthy even if some HTTP process responds", async () => {
  const { options } = harness({ site_running: true, database_running: true, database_healthy: false });
  const report = await operate("status", options);
  assert.equal(report.result, "FAIL");
  assert.equal(report.health.result, "PASS");
});
test("a replaced lock cannot be removed by an earlier owner", async () => {
  const directory = await scratch();
  try {
    const release = await acquireLock(directory);
    await fs.writeFile(path.join(directory, "operation.lock"), JSON.stringify({ token: "other-owner" }));
    await assert.rejects(release(), error => error.code === "LOCK_OWNERSHIP_CHANGED");
    assert.equal(JSON.parse(await fs.readFile(path.join(directory, "operation.lock"), "utf8")).token, "other-owner");
  } finally {
    await fs.unlink(path.join(directory, "operation.lock"));
    await fs.rmdir(directory);
  }
});
test("PowerShell parser accepts the production launcher without changing execution policy", { skip: process.platform !== "win32" }, async () => {
  const file = path.join(workspace, "tools/dev/site.ps1").replaceAll("'", "''");
  const command = "$errors=$null; $tokens=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile('" +
    file + "',[ref]$tokens,[ref]$errors); if ($errors.Count) { exit 1 }; 'PS_PARSE_OK'";
  const result = await execute("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", command],
    { cwd: workspace, windowsHide: true, shell: false });
  assert.match(result.stdout, /PS_PARSE_OK/);
});
