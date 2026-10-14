import assert from "node:assert/strict";
import { randomBytes, createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import * as fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const baseDir = path.dirname(fileURLToPath(import.meta.url));
export const imageFor = (major) => major === 18 ? "postgres:18.6-bookworm" : "postgres:17.11-bookworm";

export function parseMajor(value = "18") {
  if (!["18", "17"].includes(String(value))) {
    throw new Error("Only PostgreSQL 18 and the isolated 17 fallback are supported");
  }
  return Number(value);
}

export function parsePort(text) {
  const lines = text.split(/\r?\n/).filter((line) => line && !line.startsWith("#"));
  assert.equal(lines.length, 1, "The env file must contain only FATWA_DEV_PORT");
  const match = /^FATWA_DEV_PORT=(\d{4,5})$/.exec(lines[0]);
  assert.ok(match, "Expected FATWA_DEV_PORT=<unprivileged port>");
  const port = Number(match[1]);
  assert.ok(port >= 1024 && port <= 65535, "Port must be between 1024 and 65535");
  return String(port);
}

export function assertLocalEndpoint(endpoint) {
  assert.ok(/^(unix:\/\/\/[^\r\n]+|npipe:\/\/\/\/\.\/pipe\/[^\r\n]+)$/.test(endpoint),
    "Only local Unix socket or Windows named-pipe Docker endpoints are permitted");
  return endpoint;
}

export function validateCompose(config, major) {
  assert.deepEqual(Object.keys(config.services), ["postgres"], "Unexpected service");
  const service = config.services.postgres;
  assert.equal(config.name, "fatwa-s5-dev-pg" + major);
  assert.equal(service.image, imageFor(major), "Image must match the pinned major");
  assert.equal(service.restart, "no");
  for (const forbidden of ["privileged", "network_mode", "container_name"]) {
    assert.equal(service[forbidden], undefined);
  }
  assert.deepEqual(service.networks, ["local"]);
  assert.deepEqual(config.networks, { local: { internal: true } });
  assert.deepEqual(service.security_opt, ["no-new-privileges:true"]);
  assert.deepEqual(service.ports, [{
    target: 5432, published: "$" + "{FATWA_DEV_PORT:-55432}",
    host_ip: "127.0.0.1", protocol: "tcp",
  }]);
  assert.deepEqual(service.environment, {
    POSTGRES_USER: "fatwa_bootstrap", POSTGRES_DB: "postgres",
    POSTGRES_PASSWORD_FILE: "/run/secrets/bootstrap_password",
    POSTGRES_HOST_AUTH_METHOD: "scram-sha-256",
    POSTGRES_INITDB_ARGS: "--auth-host=scram-sha-256 --data-checksums",
  });
  assert.deepEqual(config.volumes, { ["pgdata" + major]: {} });
  assert.deepEqual(service.volumes, [
    { type: "volume", source: "pgdata" + major,
      target: major === 18 ? "/var/lib/postgresql" : "/var/lib/postgresql/data" },
    { type: "bind", source: "./initdb/10-app.sh",
      target: "/docker-entrypoint-initdb.d/10-app.sh", read_only: true },
    { type: "bind", source: "./healthcheck.sh",
      target: "/opt/fatwa/healthcheck.sh", read_only: true },
    { type: "bind", source: "./smoke.sh",
      target: "/opt/fatwa/smoke.sh", read_only: true },
  ]);
  assert.deepEqual(config.secrets, {
    bootstrap_password: { file: "./.local/bootstrap-password" },
    app_password: { file: "./.local/app-password" },
  });
  assert.deepEqual(service.secrets, ["bootstrap_password", "app_password"]);
  assert.deepEqual(service.healthcheck.test, ["CMD", "sh", "/opt/fatwa/healthcheck.sh"]);
  assert.equal(service.healthcheck.retries, 30);
  return config;
}

export async function loadCompose(major, directory = baseDir) {
  return validateCompose(JSON.parse(
    await fs.readFile(path.join(directory, "compose.pg" + major + ".yaml"), "utf8"),
  ), major);
}

async function privateLocal(directory) {
  const local = path.join(directory, ".local");
  try {
    const entry = await fs.lstat(local);
    assert.ok(entry.isDirectory() && !entry.isSymbolicLink(), ".local must be a real directory, never a symlink");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  await fs.mkdir(local, { recursive: true, mode: 0o700 });
  await fs.chmod(local, 0o700);
  return local;
}

export async function prepare(directory = baseDir) {
  // Refuse all overwrites, including a partially prepared directory.
  for (const target of [".env", ".local/bootstrap-password", ".local/app-password"]) {
    try {
      await fs.lstat(path.join(directory, target));
      throw new Error("Refusing to overwrite " + target + "; existing credentials are retained");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  // File secrets keep host ownership. Mode 0644 is readable by the container
  // postgres UID; the enclosing private directory protects files on the host.
  await privateLocal(directory);
  await fs.copyFile(path.join(directory, ".env.example"), path.join(directory, ".env"), 1);
  for (const file of ["bootstrap-password", "app-password"]) {
    await fs.writeFile(path.join(directory, ".local", file), randomBytes(32).toString("hex") + "\n",
      { flag: "wx", mode: 0o644 });
  }
}

export function runCommand(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8", windowsHide: true, timeout: 180000,
    maxBuffer: 4 * 1024 * 1024, ...options, shell: false,
  });
  if (result.error) throw new Error(command + ": " + result.error.message);
  if (result.status !== 0) {
    throw new Error(command + " failed (exit " + result.status + "):\n" +
      (result.stderr || result.stdout));
  }
  return result.stdout.trim();
}

export function preflight(run = runCommand, environment = process.env) {
  const endpoint = assertLocalEndpoint(environment.DOCKER_HOST ||
    run("docker", ["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]));
  const env = { ...environment, DOCKER_HOST: endpoint };
  delete env.DOCKER_CONTEXT;
  const version = run("docker", ["info", "--format", "{{.ServerVersion}}"], { env });
  assert.ok(version, "Docker daemon did not return a server version");
  assert.ok(Number(version.split(".")[0]) >= 28, "Docker Engine 28+ is required for safe localhost port publishing");
  const compose = environment.FATWA_COMPOSE_EXE
    ? { command: environment.FATWA_COMPOSE_EXE, prefix: [] }
    : { command: "docker", prefix: ["compose"] };
  const composeVersion = run(compose.command, [...compose.prefix, "version", "--short"], { env });
  assert.ok(/^v?[2-9]\./.test(composeVersion), "Docker Compose v2 or newer is required");
  return { ...compose, env, version, composeVersion };
}

export function composeArgs(major, directory = baseDir, envFile = ".env") {
  return ["--project-name", "fatwa-s5-dev-pg" + major, "--project-directory", directory,
    "--env-file", path.join(directory, envFile),
    "--file", path.join(directory, "compose.pg" + major + ".yaml")];
}

export async function createSmokePlan(major, directory = baseDir) {
  const config = await loadCompose(major, directory);
  const local = await privateLocal(directory);
  const temp = await fs.mkdtemp(path.join(local, "smoke-"));
  const project = "fatwa-s5-smoke-pg" + major + "-" + randomBytes(8).toString("hex");
  delete config.name;
  config.services.postgres.ports = [];
  for (const mount of config.services.postgres.volumes) {
    if (mount.type === "bind") mount.source = path.resolve(directory, mount.source);
  }
  for (const [secret, filename] of [
    ["bootstrap_password", "bootstrap-password"], ["app_password", "app-password"],
  ]) {
    const target = path.join(temp, filename);
    await fs.writeFile(target, randomBytes(32).toString("hex") + "\n", { flag: "wx", mode: 0o644 });
    config.secrets[secret].file = target;
  }
  config.services.postgres.labels["org.fatwa.smoke-project"] = project;
  const file = path.join(temp, "compose.yaml");
  await fs.writeFile(file, JSON.stringify(config, null, 2) + "\n");
  const fixtureSha = createHash("sha256").update(await fs.readFile(path.join(directory, "smoke.sh"))).digest("hex");
  return { project, file, temp, major, config, fixtureSha };
}

export function smokeArgs(plan) {
  assert.match(plan.project, /^fatwa-s5-smoke-pg(17|18)-[a-f0-9]{16}$/);
  assert.equal(plan.config.services.postgres.labels["org.fatwa.smoke-project"], plan.project);
  assert.deepEqual(plan.config.services.postgres.ports, []);
  assert.deepEqual(plan.config.volumes, { ["pgdata" + plan.major]: {} });
  assert.deepEqual(Object.keys(plan.config.services), ["postgres"]);
  return ["--project-name", plan.project, "--file", plan.file];
}

export async function runSmoke(plan, runtime, run = runCommand) {
  const args = smokeArgs(plan);
  const call = (tail) => run(runtime.command, [...runtime.prefix, ...args, ...tail], { env: runtime.env });
  let primary;
  try {
    call(["config", "--quiet"]);
    call(["up", "--detach", "--wait", "--wait-timeout", "120"]);
    console.log(call(["images", "--format", "json"]));
    const execArgs = ["exec", "-T", "--env", "FATWA_EXPECTED_MAJOR=" + plan.major,
      "postgres", "sh", "/opt/fatwa/smoke.sh"];
    console.log(call([...execArgs, "prepare"]));
    // Recreate to verify persistent volumes rather than only a live process.
    call(["up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "120"]);
    console.log(call([...execArgs, "verify"]));
  } catch (error) {
    primary = error;
  } finally {
    try {
      smokeArgs(plan);
      call(["down", "--volumes", "--remove-orphans", "--timeout", "10"]);
      // Only direct files created here; no recursive deletion or global prune.
      for (const filename of ["compose.yaml", "bootstrap-password", "app-password"]) {
        await fs.unlink(path.join(plan.temp, filename));
      }
      await fs.rmdir(plan.temp);
    } catch (cleanup) {
      throw new Error((primary ? primary.message + "\n" : "") + "Smoke cleanup failed: " +
        cleanup.message + ". Inspect generated project " + plan.project + "; no global prune.");
    }
  }
  if (primary) throw primary;
}

async function main() {
  const [command = "help", majorArg = "18", ...extra] = process.argv.slice(2);
  assert.equal(extra.length, 0, "Unexpected arguments");
  const major = parseMajor(majorArg);
  if (command === "prepare") {
    await prepare();
    console.log("Prepared ignored development files; credentials were not printed.");
    return;
  }
  if (command === "validate") {
    for (const version of [18, 17]) await loadCompose(version);
    console.log("PASS: both Compose documents parse and satisfy infrastructure boundaries.");
    return;
  }
  if (!["preflight", "up", "down", "ready", "smoke"].includes(command)) {
    if (command !== "help") throw new Error("Unknown command: " + command);
    console.log("Usage: node infra/dev/dev.mjs prepare|validate|preflight|up|down|ready|smoke [18|17]");
    return;
  }
  const runtime = preflight();
  if (command === "preflight") {
    console.log("PASS: local Docker " + runtime.version + ", Compose " + runtime.composeVersion);
    return;
  }
  if (command === "smoke") {
    const plan = await createSmokePlan(major);
    console.log("Synthetic fixture: s5-synthetic-v1; smoke.sh SHA256 " + plan.fixtureSha);
    console.log("Git HEAD: " + runCommand("git", ["rev-parse", "HEAD"], { cwd: baseDir }));
    await runSmoke(plan, runtime);
    console.log("PASS: PostgreSQL " + major + " synthetic smoke and scoped cleanup");
    return;
  }
  await loadCompose(major);
  const port = parsePort(await fs.readFile(path.join(baseDir, ".env"), "utf8"));
  const env = { ...runtime.env, FATWA_DEV_PORT: port };
  const tail = command === "up" ? ["up", "--detach", "--wait", "--wait-timeout", "120"]
    : command === "down" ? ["down", "--timeout", "10"]
      : ["exec", "-T", "postgres", "sh", "/opt/fatwa/healthcheck.sh"];
  const output = runCommand(runtime.command, [...runtime.prefix, ...composeArgs(major), ...tail], { env });
  if (output) console.log(output);
  console.log("PASS: " + command + " for fatwa-s5-dev-pg" + major + "; persistent volumes retained.");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error("FAIL: " + error.message);
    process.exitCode = 1;
  });
}
