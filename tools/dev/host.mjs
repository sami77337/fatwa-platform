// One-click HOST continuation. Existing local Docker objects only; no shell strings.
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { main as operationalMain } from "./local.mjs";

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
    "--entrypoint", "python", site.Image, "/site/tools/dev/container_workflow.py", "--verify-source"];
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
  return { result: "PASS", scope: "Live HTTP, edition, roots, depth-five path, original fields, nested children, search and SSR; GET-only checks. Browser/mobile NOT_RUN." };
}

// Preserve pinned legacy source helpers; lifecycle always uses the no-import A6 runner.
export const main = operationalMain;

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
