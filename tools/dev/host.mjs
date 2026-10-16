// One-click HOST continuation. Existing local Docker objects only; no shell strings.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execute = promisify(execFile);
export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const base = path.resolve(root, "../..");
export const pins = {
  archive: "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce",
  mapped: "b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7",
};
const networkName = "fatwa-s5-dev-pg18_local";
const siteName = "fatwa-site-v1";
export const locations = {
  archive: path.join(base, "inputs/starter/FATWA_CODEX_START_20261013/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip"),
  secret: path.join(base, "worktrees/S5/infra/dev/.local/app-password"),
  wheels: path.join(base, "control/wheels/py313-linux"),
};

export function localEndpoint(endpoint) {
  assert.match(endpoint, /^(npipe:\/\/\/\/\.\/pipe\/[^\r\n]+|unix:\/\/\/[^\r\n]+)$/,
    "Docker must use an existing local named pipe or Unix socket");
  return endpoint;
}

export function cleanEnvironment(environment) {
  const env = { ...environment };
  for (const key of Object.keys(env)) {
    if (/^(PG|DATABASE_URL$|DJANGO_SECRET_KEY$|FATWA_PRODUCTION$)/i.test(key)) delete env[key];
  }
  delete env.DOCKER_CONTEXT;
  return env;
}

export function mountPath(value) {
  return value.replaceAll("\\", "/").replace(/^\/(?:run\/desktop\/mnt\/host|host_mnt)\/([a-z])\//i, "$1:/")
    .replace(/\/$/, "").toLowerCase();
}

export function validateTopology(site, database, network) {
  assert.equal(network.Name, networkName);
  assert.equal(network.Internal, true, "PostgreSQL network must remain internal");
  assert.equal(database.Config.Labels?.["com.docker.compose.project"], "fatwa-s5-dev-pg18");
  assert.equal(database.Config.Labels?.["com.docker.compose.service"], "postgres");
  assert.equal(database.Config.Image, "postgres:18.6-bookworm");
  assert.deepEqual(Object.keys(database.NetworkSettings.Networks), [networkName]);
  if (database.State.Running) assert.ok(network.Containers?.[database.Id], "Existing PostgreSQL container must be on the internal network");
  for (const bindings of Object.values(database.HostConfig.PortBindings ?? {})) {
    for (const binding of bindings ?? []) assert.equal(binding.HostIp, "127.0.0.1", "DB has non-loopback port exposure");
  }
  assert.equal(site.Name, "/" + siteName);
  assert.equal(site.HostConfig.Privileged, false);
  assert.ok(!["host", "container"].includes(site.HostConfig.NetworkMode));
  const nets = Object.keys(site.NetworkSettings.Networks).sort();
  assert.deepEqual(nets, ["bridge", networkName].sort(), "Unexpected site network");
  assert.deepEqual(site.HostConfig.PortBindings, { "8000/tcp": [{ HostIp: "127.0.0.1", HostPort: "8000" }] },
    "Site must publish only 127.0.0.1:8000");
  for (const source of [root, locations.secret]) {
    assert.ok(site.Mounts.some(m => m.Type === "bind" && mountPath(m.Source) === mountPath(source) && m.RW === false),
      "Existing code and app-password mounts must be read-only");
  }
  const env = Object.fromEntries(site.Config.Env.map(item => {
    const index = item.indexOf("="); return [item.slice(0, index), item.slice(index + 1)];
  }));
  assert.equal(env.PGDATABASE, "fatwa_reference");
  assert.equal(env.PGUSER, "fatwa_app");
  assert.equal(env.FATWA_PRODUCTION ?? "0", "0");
  assert.ok(!env.PGPASSWORD, "Password must be loaded from the existing file, not Docker environment");
  assert.equal(env.PGPORT ?? "5432", "5432");
  const dbNetwork = database.NetworkSettings.Networks[networkName];
  const databaseHosts = [database.Name.replace(/^\//, ""), ...(dbNetwork.Aliases ?? []), ...(dbNetwork.DNSNames ?? []), dbNetwork.IPAddress].filter(Boolean);
  assert.ok(databaseHosts.includes(env.PGHOST), "The site must target the inspected local PostgreSQL container");
  assert.ok(site.Mounts.some(m => mountPath(m.Source) === mountPath(locations.secret) && m.Destination === "/run/secrets/app-password" && m.RW === false));
  assert.equal(env.DJANGO_SETTINGS_MODULE, "config.settings.development");
}

export function workerArgs(site, database, suffix) {
  return ["run", "--rm", "--pull=never", "--name", "fatwa-site-v1-accept-" + suffix,
    "--network", networkName, "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
    "--tmpfs", "/tmp:rw,nosuid,nodev,exec,size=536870912", "--workdir", "/site",
    "--mount", "type=bind,source=" + root + ",target=/site,readonly",
    "--mount", "type=bind,source=" + locations.archive + ",target=/source/book622.zip,readonly",
    "--mount", "type=bind,source=" + locations.secret + ",target=/run/secrets/app-password,readonly",
    "--mount", "type=bind,source=" + locations.wheels + ",target=/wheels,readonly",
    "--env", "PGHOST=" + database.Name.replace(/^\//, ""), "--env", "PGPORT=5432",
    "--env", "PGDATABASE=fatwa_reference", "--env", "PGUSER=fatwa_app", "--env", "FATWA_PRODUCTION=0",
    "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONUNBUFFERED=1",
    "--entrypoint", "python", site.Image, "/site/tools/dev/container_workflow.py"];
}

async function http(route, json = true, options = {}) {
  const response = await fetch("http://127.0.0.1:8000" + route,
    { redirect: "error", signal: AbortSignal.timeout(10000), ...options });
  assert.equal(response.status, 200, "HTTP failed: " + route);
  return json ? response.json() : response.text();
}

export async function checkHttp(worker) {
  const edition = worker.edition_id;
  const books = await http("/api/v1/fiqh/books?limit=100");
  const book = books.items.find(item => item.id === edition);
  assert.ok(book, "Imported edition is absent from HTTP");
  assert.equal(book.source_archive_sha256, pins.archive);
  assert.equal(book.heading_count, 11397);
  assert.equal(book.root_count, 32);
  assert.equal(book.max_depth, 5);
  const roots = await http("/api/v1/fiqh/roots?edition=" + edition + "&limit=100");
  assert.equal(roots.total, 32);
  assert.equal(roots.items.length, 32);
  const page = await http("/fiqh", false);
  assert.match(page, /lang="ar" dir="rtl"/);
  assert.match(page, /reference\/catalog.js/);
  await http("/readyz");
  const status = await http("/api/v1/status");
  assert.equal(status.sensitive_write_routes_enabled, false);
  assert.equal(status.fatwa_publications_available, false);
  for (const expected of worker._probes) {
    const detail = await http("/api/v1/fiqh/nodes/" + expected.id + "?edition=" + edition);
    for (const [key, value] of Object.entries(expected)) {
      if (key !== "path") assert.deepEqual(detail.node[key], value, "Node field differs: " + key);
    }
    assert.deepEqual(detail.ancestors.map(item => item.id), expected.path);
    const basic = await http("/fiqh/nodes/" + expected.id + "?basic=1&edition=" + edition, false);
    assert.ok(basic.includes(expected.title));
    for (const mode of ["exact", "literal", "normalized"]) {
      const results = await http("/api/v1/fiqh/search?edition=" + edition + "&mode=" + mode +
        "&limit=100&q=" + encodeURIComponent(expected.title));
      assert.ok(results.items.some(item => item.id === expected.id), "Search did not find original heading");
    }
    if (expected.parent_id !== null) {
      const children = await http("/api/v1/fiqh/nodes/" + expected.parent_id + "/children?edition=" + edition + "&anchor=" + expected.id);
      assert.ok(children.items.some(item => item.id === expected.id), "Nested child is absent");
    }
  }
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    const response = await fetch("http://127.0.0.1:8000/api/v1/fiqh/search", { method, signal: AbortSignal.timeout(5000) });
    assert.equal(response.status, 405);
  }
  return { result: "PASS", scope: "Live HTTP, edition, roots, depth-five path, original fields, nested children, search, SSR, denied writes. Browser/mobile NOT_RUN." };
}

export async function main() {
  const report = { timestamp: new Date().toISOString(), REAL_SOURCE_DATABASE_IMPORT: "NOT_RUN",
    DJANGO_SITE_HTTP: "NOT_RUN", REAL_CATALOG_HTTP: "NOT_RUN", gates: "NOT_DEPLOYED / GATES_HOLD" };
  const local = path.join(root, ".local");
  await fs.mkdir(local, { recursive: true });
  let lock;
  let env;
  const run = async args => {
    try {
      const result = await execute("docker", args, { cwd: root, env, windowsHide: true,
        timeout: 900000, maxBuffer: 4 * 1024 * 1024 });
      return result.stdout.trim();
    } catch (error) {
      // The worker returns structured evidence even when its phase fails.
      if (args[0] === "run" && error.stdout?.trim().startsWith("{")) return error.stdout.trim();
      throw new Error("Docker operation " + args[0] + " failed: " + (error.stderr || error.message).slice(0,1800));
    }
  };
  try {
    try {
      const html = await http("/fiqh", false);
      assert.match(html, /lang="ar" dir="rtl"/);
      await http("/readyz");
      const inventory = await http("/api/v1/fiqh/books");
      report.DJANGO_SITE_HTTP = "PASS";
      report.current_http_inventory = { editions: inventory.total };
    } catch { /* A stopped site can be started after the verified import. */ }
    lock = await fs.open(path.join(local, "host-run.lock"), "wx");
    await lock.writeFile(String(process.pid));
    const bytes = await fs.readFile(locations.archive);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), pins.archive, "Owner archive SHA256 mismatch");
    assert.ok((await fs.stat(locations.secret)).isFile(), "Existing app-password file missing");
    assert.ok((await fs.stat(locations.wheels)).isDirectory(), "Existing offline wheel directory missing");
    const branch = await execute("git", ["branch", "--show-current"], { cwd: root, windowsHide: true });
    assert.equal(branch.stdout.trim(), "codex/integration-site-v1-20261015");
    const revision = await execute("git", ["rev-parse", "HEAD"], { cwd: root, windowsHide: true });
    report.code_sha = revision.stdout.trim();
    const dirty = await execute("git", ["status", "--porcelain"], { cwd: root, windowsHide: true });
    report.working_tree_modified = Boolean(dirty.stdout.trim());
    env = cleanEnvironment(process.env);
    const endpoint = process.env.DOCKER_HOST || await run(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]);
    env.DOCKER_HOST = localEndpoint(endpoint);
    const engine = await run(["version", "--format", "{{.Server.Version}}"]);
    assert.ok(Number(engine.split(".")[0]) >= 28, "Docker Engine 28+ required for loopback publication");
    const inspect = async name => JSON.parse(await run(["inspect", name]))[0];
    const network = JSON.parse(await run(["network", "inspect", networkName]))[0];
    const candidates = await Promise.all(Object.keys(network.Containers ?? {}).map(inspect));
    const databases = candidates.filter(item => item.Config.Labels?.["com.docker.compose.project"] === "fatwa-s5-dev-pg18"
      && item.Config.Labels?.["com.docker.compose.service"] === "postgres");
    // A stopped container may not be listed in network.Containers; query only the exact existing project.
    if (!databases.length) {
      const ids = (await run(["ps", "-aq", "--filter", "label=com.docker.compose.project=fatwa-s5-dev-pg18",
        "--filter", "label=com.docker.compose.service=postgres"])).split(/\s+/).filter(Boolean);
      for (const id of ids) databases.push(await inspect(id));
    }
    assert.equal(databases.length, 1, "Exactly one existing S5 PG18 container is required");
    let database = databases[0];
    const site = await inspect(siteName);
    // Do not start or mutate anything before validating the actual topology and mounts.
    validateTopology(site, database, network);
    if (!database.State.Running) await run(["start", database.Id]);
    let ready = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      database = await inspect(database.Id);
      if (database.State.Running && database.State.Health?.Status === "healthy") { ready = true; break; }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    assert.ok(ready, "Existing PostgreSQL container did not become healthy");
    validateTopology(site, database, JSON.parse(await run(["network", "inspect", networkName]))[0]);
    console.log("Source pin and local isolation verified; running S1 preview/import/verification and tests...");
    const worker = JSON.parse(await run(workerArgs(site, database, randomUUID().slice(0,8))));
    report.REAL_SOURCE_DATABASE_IMPORT = worker.REAL_SOURCE_DATABASE_IMPORT;
    report.worker = { ...worker }; delete report.worker._probes;
    assert.equal(worker.REAL_SOURCE_DATABASE_IMPORT, "PASS", worker.blocker?.message || "Source import failed");
    if (!site.State.Running) await run(["start", site.Id]);
    let httpError;
    for (let attempt = 0; attempt < 10; attempt++) {
      try { report.http = await checkHttp(worker); httpError = null; break; }
      catch (error) { httpError = error; await new Promise(resolve => setTimeout(resolve, 1000)); }
    }
    if (httpError) throw httpError;
    report.DJANGO_SITE_HTTP = "PASS";
    report.REAL_CATALOG_HTTP = "PASS";
    const nodeTests = await execute(process.execPath, ["--test", "tests/integration/django-api.test.mjs",
      "ui_drafts/fiqh/tests/api.test.mjs", "ui_drafts/fiqh/tests/server.test.mjs", "ui_drafts/fiqh/tests/source-identity.test.mjs"],
      { cwd: root, env: { ...cleanEnvironment(process.env), FATWA_622_ARCHIVE: locations.archive }, windowsHide: true, maxBuffer: 2e6 });
    report.frontend_tests = { result: "PASS", output: nodeTests.stdout };
    if (worker.blocker || Object.values(worker.tests).some(item => item.result !== "PASS")) {
      report.blocker = "Import/site evidence is recorded; some tests did not pass or could not run. See worker.tests.";
    }
  } catch (error) {
    report.blocker = error.message;
  } finally {
    if (lock) { await lock.close(); await fs.unlink(path.join(local, "host-run.lock")); }
    await fs.writeFile(path.join(local, "host-result.json"), JSON.stringify(report, null, 2) + "\n");
  }
  console.log(JSON.stringify(report, null, 2));
  console.log("Local URL: http://127.0.0.1:8000/fiqh | Report: .local/host-result.json");
  return report.blocker ? 1 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
