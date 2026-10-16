import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { root, locations, pins, localEndpoint, cleanEnvironment, mountPath, validateTopology, workerArgs, checkHttp } from "../../tools/dev/host.mjs";

function topology() {
  const name = "fatwa-s5-dev-pg18_local";
  const database = { Id: "db-id", Name: "/fatwa-s5-dev-pg18-postgres-1", State: { Running: true },
    Config: { Image: "postgres:18.6-bookworm", Labels: { "com.docker.compose.project": "fatwa-s5-dev-pg18", "com.docker.compose.service": "postgres" } },
    HostConfig: { PortBindings: { "5432/tcp": [{ HostIp: "127.0.0.1", HostPort: "55432" }] } },
    NetworkSettings: { Networks: { [name]: { Aliases: ["postgres"], IPAddress: "172.25.0.2" } } } };
  const site = { Id: "site-id", Name: "/fatwa-site-v1", Image: "sha256:existing-python-image", State: { Running: true },
    Config: { Env: ["PGHOST=postgres", "PGPORT=5432", "PGDATABASE=fatwa_reference", "PGUSER=fatwa_app", "DJANGO_SETTINGS_MODULE=config.settings.development"] },
    HostConfig: { Privileged: false, NetworkMode: "bridge", PortBindings: { "8000/tcp": [{ HostIp: "127.0.0.1", HostPort: "8000" }] } },
    Mounts: [{ Type: "bind", Source: root, Destination: "/app", RW: false }, { Type: "bind", Source: locations.secret, Destination: "/run/secrets/app-password", RW: false }],
    NetworkSettings: { Networks: { bridge: {}, [name]: {} } } };
  return { site, database, network: { Name: name, Internal: true, Containers: { "db-id": {} } } };
}

test("only existing local Docker pipe/socket endpoints are accepted", () => {
  for (const endpoint of ["npipe:////./pipe/docker_engine", "npipe:////./pipe/dockerDesktopLinuxEngine", "unix:///var/run/docker.sock"]) assert.equal(localEndpoint(endpoint), endpoint);
  for (const endpoint of ["tcp://127.0.0.1:2375", "https://remote.example", "npipe:////./pipe/test\nremote"]) assert.throws(() => localEndpoint(endpoint));
});

test("Docker child environment excludes inherited DB credentials and production switches", () => {
  const env = cleanEnvironment({ PATH: "safe", PGPASSWORD: "synthetic-secret", DATABASE_URL: "synthetic-url", PGHOST: "remote", DJANGO_SECRET_KEY: "synthetic-key", FATWA_PRODUCTION: "1", DOCKER_CONTEXT: "remote", DOCKER_HOST: "local" });
  assert.deepEqual(env, { PATH: "safe", DOCKER_HOST: "local" });
});

test("actual topology validation refuses isolation, mount, destination and role mismatches", () => {
  const original = topology();
  assert.doesNotThrow(() => validateTopology(original.site, original.database, original.network));
  const mutations = [
    t => { t.network.Internal = false; },
    t => { t.network.Containers = {}; },
    t => { t.database.NetworkSettings.Networks.bridge = {}; },
    t => { t.database.Config.Image = "postgres:17.11-bookworm"; },
    t => { t.site.HostConfig.PortBindings["8000/tcp"][0].HostIp = "0.0.0.0"; },
    t => { t.database.HostConfig.PortBindings["5432/tcp"][0].HostIp = "0.0.0.0"; },
    t => { t.site.Mounts[0].RW = true; },
    t => { t.site.Mounts[1].Destination = "/wrong-secret"; },
    t => { t.site.Config.Env.push("PGPASSWORD=synthetic-secret"); },
    t => { t.site.Config.Env.push("PGUSER=fatwa_bootstrap"); },
    t => { t.site.Config.Env.push("PGDATABASE=production"); },
    t => { t.site.Config.Env.push("PGHOST=external.example"); },
    t => { t.site.Config.Env.push("FATWA_PRODUCTION=1"); },
  ];
  for (const mutate of mutations) {
    const data = topology(); mutate(data);
    assert.throws(() => validateTopology(data.site, data.database, data.network));
  }
});

test("worker uses immutable inspected image, internal network, offline RO mounts and app role", () => {
  const { site, database } = topology();
  const args = workerArgs(site, database, "test-id");
  assert.equal(args[args.indexOf("--network") + 1], "fatwa-s5-dev-pg18_local");
  assert.ok(args.includes(site.Image));
  assert.ok(args.includes("--pull=never"));
  assert.ok(args.includes("--rm"));
  assert.ok(args.includes("--read-only"));
  assert.ok(args.includes("PGUSER=fatwa_app"));
  assert.ok(args.includes("PGDATABASE=fatwa_reference"));
  assert.equal(args.filter(item => item.startsWith("type=bind,")).length, 4);
  assert.ok(args.filter(item => item.startsWith("type=bind,")).every(item => item.endsWith(",readonly")));
  assert.ok(!args.some(item => /PGPASSWORD=|bootstrap|publish|privileged/.test(item)));
  assert.equal(mountPath("/run/desktop/mnt/host/c/Users/Test"), "c:/users/test");
});

test("real supplied archive identity matches pin; no database acceptance is implied", async t => {
  let raw;
  try { raw = await readFile(locations.archive); }
  catch (error) { if (error.code === "ENOENT") { t.skip("Owner archive unavailable"); return; } throw error; }
  assert.equal(createHash("sha256").update(raw).digest("hex"), pins.archive);
});

test("HTTP acceptance checks source metadata, all search modes, nesting and denied writes (mock transport)", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  const sample = { id: 42, source_id: "synthetic-42", title: "عنوان اختبار", parent_id: 41, depth: 5, part: "1", page: 9, page_id: 90, source_entry_number: null, path: [1, 2, 3, 41, 42] };
  const worker = { edition_id: 7, _probes: [sample] };
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(input); requests.push([url.pathname, url.search, options.method]);
    let data;
    if (options.method) return new Response("", { status: 405 });
    if (url.pathname === "/api/v1/fiqh/books") data = { items: [{ id: 7, source_archive_sha256: pins.archive, heading_count: 11397, root_count: 32, max_depth: 5 }] };
    else if (url.pathname === "/api/v1/fiqh/roots") data = { total: 32, items: Array(32).fill({}) };
    else if (url.pathname === "/fiqh") return new Response('<html lang="ar" dir="rtl"><script src="reference/catalog.js"></script>');
    else if (url.pathname.startsWith("/fiqh/nodes/")) return new Response(sample.title);
    else if (url.pathname === "/api/v1/status") data = { sensitive_write_routes_enabled: false, fatwa_publications_available: false };
    else if (url.pathname.endsWith("/children") || url.pathname.endsWith("/search")) data = { items: [{ id: 42 }] };
    else if (url.pathname.includes("/nodes/")) data = { node: sample, ancestors: sample.path.map(id => ({ id })) };
    else data = { database_reachable: true };
    return Response.json(data);
  };
  try {
    assert.equal((await checkHttp(worker)).result, "PASS");
    assert.deepEqual(requests.filter(([p]) => p.endsWith("/search")).filter(([, , method]) => !method).map(([, q]) => new URLSearchParams(q).get("mode")), ["exact", "literal", "normalized"]);
    assert.equal(requests.filter(([, , method]) => method).length, 4);
    assert.ok(requests.some(([, q]) => q.includes("anchor=42")));
  } finally { globalThis.fetch = originalFetch; }
});
