// A6 local operation. Never provision, import, migrate, or change the database.
import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { healthcheck, origin, readLocal } from "./health.mjs";

const execute = promisify(execFile);
export const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export const siteName = "fatwa-site-v1";
export const databaseName = "fatwa-s5-dev-pg18-postgres-1";
export const networkName = "fatwa-s5-dev-pg18_local";
export const actions = Object.freeze(["start", "restart", "status", "healthcheck", "test", "test-db"]);
export const stateDirectory = path.join(workspace, "tools/dev/.local");

export class OperationError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
function requireSafe(condition, code, message) {
  if (!condition) throw new OperationError(code, message);
}
export function parseArguments(argv) {
  requireSafe(argv.length <= 1 && (argv.length === 0 || actions.includes(argv[0]) || argv[0] === "--help"),
    "INVALID_ARGUMENTS", "Use one action: start, restart, status, healthcheck, test, or test-db.");
  return argv[0] ?? "start";
}
export function dockerEndpoint(endpoint) {
  requireSafe(typeof endpoint === "string" &&
    /^(npipe:\/\/\/\/\.\/pipe\/[a-zA-Z0-9_.-]+|unix:\/\/\/[a-zA-Z0-9_./ -]+)$/.test(endpoint),
    "REMOTE_DOCKER_REFUSED", "Docker must use an existing local named pipe or Unix socket.");
  return endpoint;
}
export function childEnvironment(environment) {
  const env = { ...environment };
  for (const key of Object.keys(env)) {
    if (/^(PG|DATABASE_URL$|DJANGO_|FATWA_|DOCKER_(HOST|CONTEXT|TLS_VERIFY|CERT_PATH)$|NODE_OPTIONS$|NODE_USE_ENV_PROXY$|.*(?:PASSWORD|SECRET|TOKEN|API_KEY)$)/i.test(key)) delete env[key];
  }
  return env;
}
function mountKey(value) {
  const mapped = String(value).replaceAll("\\", "/")
    .replace(/^\/(?:run\/desktop\/mnt\/host|host_mnt)\/([a-z])\//i, "$1:/").replace(/\/$/, "");
  return /^[a-z]:/i.test(mapped) ? mapped.toLowerCase() : mapped;
}
function environmentOf(site) {
  const entries = site.Config?.Env ?? [];
  const env = {};
  for (const item of entries) {
    const split = item.indexOf("=");
    requireSafe(split > 0, "INVALID_CONTAINER_ENV", "Invalid container environment.");
    const key = item.slice(0, split);
    requireSafe(!Object.hasOwn(env, key), "INVALID_CONTAINER_ENV", "Duplicate container environment.");
    env[key] = item.slice(split + 1);
  }
  return env;
}
export function validateSite(site, database, network, projectRoot = workspace) {
  // Explicit error messages avoid reflecting Docker inspect values, commands or credentials.
  requireSafe(site?.Name === "/" + siteName && database?.Name === "/" + databaseName,
    "WRONG_CONTAINER", "Only the explicitly named existing local site is supported.");
  requireSafe(network?.Name === networkName && network.Internal === true &&
    network.Driver === "bridge", "UNSAFE_NETWORK", "The existing PostgreSQL network must remain internal.");
  requireSafe(database.Config?.Labels?.["com.docker.compose.project"] === "fatwa-s5-dev-pg18" &&
    database.Config?.Labels?.["com.docker.compose.service"] === "postgres" &&
    database.Config?.Image === "postgres:18.6-bookworm",
    "WRONG_DATABASE_CONTAINER", "The expected existing PostgreSQL 18 container is required.");
  requireSafe(JSON.stringify(Object.keys(database.NetworkSettings?.Networks ?? {}).sort()) === JSON.stringify([networkName]) &&
    database.HostConfig?.Privileged === false &&
    database.HostConfig?.NetworkMode !== "host" &&
    !database.HostConfig?.NetworkMode?.startsWith("container:"),
    "UNSAFE_DATABASE_NETWORK", "The database must retain its isolated existing network.");
  for (const [port, bindings] of Object.entries(database.HostConfig?.PortBindings ?? {})) {
    requireSafe(port === "5432/tcp" && Array.isArray(bindings) && bindings.every(binding =>
      binding.HostIp === "127.0.0.1" && binding.HostPort === "55432"),
    "UNSAFE_DATABASE_PORT", "Unexpected database port exposure.");
  }
  requireSafe(site.HostConfig?.Privileged === false && site.HostConfig?.NetworkMode !== "host" &&
    !site.HostConfig?.NetworkMode?.startsWith("container:"),
    "UNSAFE_SITE_NETWORK", "Host/shared container networking is forbidden.");
  requireSafe(JSON.stringify(Object.keys(site.NetworkSettings?.Networks ?? {}).sort()) ===
    JSON.stringify(["bridge", networkName].sort()),
    "UNSAFE_SITE_NETWORK", "Unexpected site network attachment.");
  const ports = site.HostConfig?.PortBindings ?? {};
  requireSafe(Object.keys(ports).length === 1 && Array.isArray(ports["8000/tcp"]) &&
    ports["8000/tcp"].length === 1 && ports["8000/tcp"][0].HostIp === "127.0.0.1" &&
    ports["8000/tcp"][0].HostPort === "8000" && !site.HostConfig?.PublishAllPorts,
    "UNSAFE_SITE_PORT", "The site must publish only 127.0.0.1:8000.");
  const mounts = site.Mounts ?? [];
  const code = mounts.filter(m => m.Type === "bind" && ["/app", "/site"].includes(m.Destination));
  requireSafe(code.length === 1 && code[0].RW === false &&
    mountKey(code[0].Source) === mountKey(projectRoot),
    "WRONG_WORKTREE_MOUNT", "The site must mount THIS A6 copy read-only. No original or sibling copy will be restarted.");
  const secret = mounts.filter(m => m.Type === "bind" && m.Destination === "/run/secrets/app-password");
  requireSafe(secret.length === 1 && secret[0].RW === false && mounts.length === 2,
    "UNSAFE_MOUNTS", "Only the existing read-only code and application credential mounts are permitted.");
  const env = environmentOf(site);
  requireSafe(env.PGDATABASE === "fatwa_reference" && env.PGUSER === "fatwa_app" &&
    (env.PGPORT ?? "5432") === "5432" && (env.FATWA_PRODUCTION ?? "0") === "0" &&
    !env.PGPASSWORD && !env.DATABASE_URL && env.DJANGO_SETTINGS_MODULE === "config.settings.development",
    "UNSAFE_DATABASE_SETTINGS", "Unexpected site database, credential, role, or settings configuration.");
  const dbNet = database.NetworkSettings.Networks[networkName];
  const hosts = [databaseName, ...(dbNet.Aliases ?? []), ...(dbNet.DNSNames ?? []), dbNet.IPAddress].filter(Boolean);
  requireSafe(hosts.includes(env.PGHOST), "WRONG_DATABASE_HOST", "The site must target the inspected local PostgreSQL container.");
  const command = [...(site.Config.Entrypoint ?? []), ...(site.Config.Cmd ?? [])].join(" ");
  requireSafe(/\brunserver\s+(?:0\.0\.0\.0|127\.0\.0\.1):8000\b/.test(command) &&
    !/\b(?:migrate|makemigrations|import_book622|flush|dropdb|createdb|reset_db|curl|wget|apt|npm|npx|ssh)\b/i.test(command) &&
    (!/\bpip(?:3)?\s+install\b/.test(command) || /--no-index\b/.test(command)),
    "UNSAFE_START_COMMAND", "The existing site command must serve Django without import, migration, or database maintenance.");
  return { site_running: site.State?.Running === true, database_running: database.State?.Running === true,
    database_healthy: database.State?.Health?.Status === "healthy" };
}

export async function makeDocker({ executeFile = execute, environment = process.env } = {}) {
  const env = childEnvironment(environment);
  let endpoint = environment.DOCKER_HOST;
  const invoke = async (args, timeout = 15000) => {
    try {
      return (await executeFile("docker", args, {
        cwd: workspace, env, shell: false, windowsHide: true, timeout, maxBuffer: 2 * 1024 * 1024,
      })).stdout.trim();
    } catch (error) {
      if (error.code === "ENOENT") throw new OperationError("DOCKER_NOT_INSTALLED", "The local Docker CLI was not found. Enable the existing Docker Desktop installation.");
      if (/No such (?:object|container|network)/i.test(error.stderr ?? "")) throw new OperationError("EXISTING_OBJECT_MISSING", "The exact existing local site, database or network was not found. No replacement will be created.");
      if (/permission denied|access is denied/i.test(error.stderr ?? "")) throw new OperationError("DOCKER_PERMISSION_DENIED", "Access to the local Docker engine was denied. Run the button in the owner session with Docker Desktop access.");
      throw new OperationError("DOCKER_UNAVAILABLE",
        "Local Docker is unavailable or permission was denied. Open Docker Desktop in the owner session and retry. Raw Docker output is omitted.");
    }
  };
  if (!endpoint) endpoint = await invoke(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]);
  endpoint = dockerEndpoint(endpoint);
  // Every daemon command explicitly uses the validated local transport.
  return args => invoke(["--host", endpoint, ...args], args[0] === "restart" ? 30000 : 15000);
}

export async function inspectSite(docker) {
  let site, database, network;
  try {
    site = JSON.parse(await docker(["inspect", "--type", "container", siteName]))[0];
    database = JSON.parse(await docker(["inspect", "--type", "container", databaseName]))[0];
    network = JSON.parse(await docker(["network", "inspect", networkName]))[0];
  } catch (error) {
    if (error instanceof OperationError) throw error;
    throw new OperationError("DOCKER_INSPECTION_FAILED", "The exact existing containers and network could not be inspected.");
  }
  const engine = await docker(["version", "--format", "{{.Server.Version}}"]);
  requireSafe(Number(engine.split(".")[0]) >= 28, "OLD_DOCKER_ENGINE", "Docker Engine 28+ is required for loopback port isolation.");
  return { site, database, network, state: validateSite(site, database, network) };
}

export async function acquireLock(directory = stateDirectory) {
  await fs.mkdir(directory, { recursive: true });
  const file = path.join(directory, "operation.lock");
  let handle;
  try { handle = await fs.open(file, "wx"); }
  catch (error) {
    if (error.code === "EEXIST") throw new OperationError("RUNNER_LOCKED",
      "Another launch/restart owns tools/dev/.local/operation.lock. Close that run first. An interrupted lock requires manual inspection; it is never deleted automatically.");
    throw error;
  }
  const token = randomUUID();
  try { await handle.writeFile(JSON.stringify({ token, pid: process.pid, started_at: new Date().toISOString() })); }
  catch (error) { await handle.close(); await fs.unlink(file); throw error; }
  return async () => {
    await handle.close();
    const owner = JSON.parse(await fs.readFile(file, "utf8"));
    requireSafe(owner.token === token, "LOCK_OWNERSHIP_CHANGED", "The operation lock ownership changed; the replacement lock was preserved.");
    await fs.unlink(file);
  };
}

export function publicFailure(error) {
  return error instanceof OperationError ? { code: error.code, message: error.message } :
    { code: "LOCAL_OPERATION_FAILED", message: "Local operation failed. No raw environment, process output, or secret values were retained." };
}

export async function waitForSite() {
  for (let attempt = 0; attempt < 12; attempt++) {
    try {
      const ready = await readLocal("/readyz", { timeoutMs: 1500 });
      if (ready.status === 200 && JSON.parse(ready.body).database_reachable === true) return;
    } catch { /* Bounded wait for the existing Django process only. */ }
    if (attempt < 11) await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new OperationError("SITE_NOT_READY", "The named site did not become ready within the bounded startup wait.");
}

export async function operate(action, {
  getDocker = makeDocker, checkHealth = healthcheck, inspect = inspectSite, lock = acquireLock,
  waitReady = waitForSite,
} = {}) {
  const report = {
    action, timestamp: new Date().toISOString(), result: "FAIL",
    site: siteName, url: origin + "/fiqh", gates: "NOT_DEPLOYED / GATES_HOLD",
    source_import: "NOT_RUN", database_migrations: "NOT_RUN", django_postgresql_tests: "NOT_RUN",
  };
  let release;
  try {
    requireSafe(["start", "restart", "status", "healthcheck"].includes(action),
      "INVALID_ARGUMENTS", "Unsupported operation.");
    if (action !== "healthcheck") {
      if (action !== "status") release = await lock();
      const docker = await getDocker();
      const topology = await inspect(docker);
      report.container = { result: "PASS", ...topology.state };
      if (action !== "status") {
        requireSafe(topology.state.database_running && topology.state.database_healthy,
          "DATABASE_NOT_READY", "The existing database must already be running and healthy. This launcher never starts or changes it.");
        if (action === "restart") {
          await docker(["restart", "--time", "10", siteName]);
          report.container_action = "RESTARTED_NAMED_SITE";
          await waitReady();
        } else if (!topology.state.site_running) {
          await docker(["start", siteName]);
          report.container_action = "STARTED_NAMED_SITE";
          await waitReady();
        } else report.container_action = "ALREADY_RUNNING";
      }
    }
    report.health = await checkHealth();
    report.result = report.health.result === "PASS" ? "PASS" : "FAIL";
    if (action === "status" && (!report.container.site_running || !report.container.database_running || !report.container.database_healthy)) report.result = "FAIL";
  } catch (error) {
    report.failure = publicFailure(error);
    // Record working live HTTP independently even when Docker access/ownership fails.
    try { report.health = await checkHealth(); }
    catch { report.health = { result: "FAIL", reason: "HEALTHCHECK_UNAVAILABLE" }; }
  } finally {
    if (release) {
      try { await release(); }
      catch { report.result = "FAIL"; report.failure = { code: "LOCK_RELEASE_FAILED", message: "The operation lock could not be released." }; }
    }
  }
  return report;
}

export async function unitTests({ executeFile = execute } = {}) {
  const files = (await fs.readdir(path.join(workspace, "tests/dev"))).filter(name => name.endsWith(".test.mjs")).sort();
  const args = ["--test", "--test-reporter=tap", ...files.map(name => "tests/dev/" + name)];
  try {
    const output = await executeFile(process.execPath, args, { cwd: workspace,
      env: childEnvironment(process.env), shell: false, windowsHide: true, timeout: 60000, maxBuffer: 2 * 1024 * 1024 });
    const totals = {};
    for (const match of output.stdout.matchAll(/^# (tests|pass|fail|skipped) (\d+)$/gm)) totals[match[1]] = Number(match[2]);
    return { result: "PASS", scope: "Node launcher regressions, synthetic/mock tests; no live DB acceptance.", totals };
  } catch {
    return { result: "FAIL", code: "REGRESSION_TESTS_FAILED",
      message: "Run node --test tests/dev/*.test.mjs for individual assertions. Raw process output is omitted." };
  }
}

export async function writeReport(action, report, directory = stateDirectory) {
  await fs.mkdir(directory, { recursive: true });
  const target = path.join(directory, "a6-" + action + "-result.json");
  const temporary = target + "." + randomUUID() + ".tmp";
  try {
    await fs.writeFile(temporary, JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
    await fs.rename(temporary, target);
  } finally {
    await fs.unlink(temporary).catch(error => { if (error.code !== "ENOENT") throw error; });
  }
}

export async function main(argv = process.argv.slice(2)) {
  let action;
  try { action = parseArguments(argv); }
  catch (error) { console.error(publicFailure(error).message); return 2; }
  if (action === "--help") {
    console.log("START_LOCAL.cmd [start|restart|status|healthcheck|test|test-db]\nDefault: start the existing verified site; open the local URL shown after PASS.\nNo import, migrations, database changes, credentials, provisioning, or remote Docker.");
    return 0;
  }
  let report;
  if (action === "test") {
    report = { action, timestamp: new Date().toISOString(), ...(await unitTests()), django_postgresql_tests: "NOT_RUN" };
  } else if (action === "test-db") {
    report = { action, timestamp: new Date().toISOString(), result: "NOT_RUN",
      code: "DATABASE_ISOLATION_NOT_PROVEN", django_postgresql_tests: "NOT_RUN",
      message: "Django database tests are disabled. A separate database name and --keepdb do not prove isolation. See docs/operations/A6_LOCAL_OPERATION.md and tools/dev/db_test_guard.py.",
      source_import: "NOT_RUN", database_migrations: "NOT_RUN" };
  } else report = await operate(action);
  try {
    const revision = await execute("git", ["rev-parse", "HEAD"], {
      cwd: workspace, env: { ...childEnvironment(process.env), GIT_OPTIONAL_LOCKS: "0" },
      shell: false, windowsHide: true, timeout: 5000,
    });
    report.code_sha = /^[a-f0-9]{40,64}$/.test(revision.stdout.trim()) ? revision.stdout.trim() : "UNVERIFIED";
    report.working_tree = "Includes local A6 edits; commit SHA alone does not identify uncommitted tooling.";
  } catch { report.code_sha = "UNVERIFIED"; }
  report.workspace_path_sha256 = createHash("sha256").update(workspace).digest("hex");
  try { await writeReport(action, report); }
  catch { report.result = "FAIL"; report.failure = { code: "REPORT_WRITE_FAILED", message: "Could not save the local action report." }; }
  console.log(JSON.stringify(report, null, 2));
  console.log("Local URL: " + origin + "/fiqh | Report: tools/dev/.local/a6-" + action + "-result.json");
  return report.result === "PASS" ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
