import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runCommand } from "./dev.mjs";

export const repoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export const stages = ["install", "lint", "format", "type", "system", "migration", "tests"];
const modules = { install: "pip", lint: "ruff", format: "ruff", type: "mypy", tests: "pytest" };

export function safeRelative(value) {
  assert.equal(typeof value, "string");
  assert.ok(value && !path.isAbsolute(value) && !value.includes("\\") &&
    !value.split("/").includes("..") && !/^[A-Za-z]:/.test(value) && !value.includes("\0") && !value.startsWith("-"), "Unsafe repository path");
  return value;
}

export function validateContract(contract) {
  assert.equal(contract.version, 1);
  assert.equal(contract.status, "S0_COMMITTED_COMMANDS_CONFIRMED");
  assert.match(contract.settings_module, /^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$/);
  assert.ok(Array.isArray(contract.dependency_files) && contract.dependency_files.length > 0);
  contract.dependency_files.forEach(safeRelative);
  assert.deepEqual(Object.keys(contract.commands).sort(), [...stages].sort());
  for (const stage of stages) {
    const commands = contract.commands[stage];
    assert.ok(Array.isArray(commands) && commands.length > 0, "Missing stage: " + stage);
    for (const args of commands) {
      assert.ok(Array.isArray(args) && args.length > 2 && args.every(x => typeof x === "string"));
      assert.equal(args[0], "python", "Commands must use the selected Python runtime");
      if (args[1] === "manage.py") {
        assert.ok(["system", "migration", "tests"].includes(stage));
        assert.equal(args[2], { system: "check", migration: "makemigrations", tests: "test" }[stage]);
      } else {
        assert.equal(args[1], "-m");
        assert.equal(args[2], modules[stage], "Unexpected module for " + stage);
      }
      if (stage === "install") {
        assert.equal(args[3], "install");
        assert.ok(args.includes(".") || contract.dependency_files.some(
          file => args.some((arg, i) => ["-r", "--requirement"].includes(arg) && args[i + 1] === file),
        ), "Install must reference declared S0 dependencies");
      }
      if (stage === "lint") assert.equal(args[3], "check");
      if (stage === "format") {
        assert.equal(args[3], "format");
        assert.ok(args.includes("--check"), "Formatting must be read-only in CI");
      }
      if (stage === "migration") {
        assert.ok(args.includes("--check") && args.includes("--dry-run"), "No migration writes in CI");
      }
    }
  }
  assert.ok(contract.database_env && Object.keys(contract.database_env).length > 0);
  for (const [name, field] of Object.entries(contract.database_env)) {
    assert.match(name, /^[A-Z][A-Z0-9_]*$/);
    assert.ok(["url", "host", "port", "name", "user", "password"].includes(field));
    assert.ok(!["PATH", "HOME", "PYTHONPATH", "DOCKER_HOST", "GITHUB_ENV"].includes(name));
  }
  return contract;
}

export async function detectApplication(directory = repoDir, isCommitted = undefined) {
  try { await fs.access(path.join(directory, "manage.py")); }
  catch (error) {
    if (error.code !== "ENOENT") throw error;
    return { available: false, reason: "manage.py absent; S0 has not been integrated" };
  }
  const contractFile = "infra/dev/application-contract.json";
  let contract;
  try {
    contract = validateContract(JSON.parse(await fs.readFile(path.join(directory, contractFile), "utf8")));
  } catch (error) {
    throw new Error("S0 code present but integration contract is missing/invalid: " + error.message);
  }
  const committed = isCommitted || (async (file) => {
    try {
      const fromCommit = runCommand("git", ["show", "HEAD:" + file], { cwd: directory });
      const local = await fs.readFile(path.join(directory, file), "utf8");
      return fromCommit === local.replace(/\r\n/g, "\n").trim();
    } catch { return false; }
  });
  for (const file of ["manage.py", contractFile, ...contract.dependency_files]) {
    assert.ok(await committed(file), "Integration file must exist in checked-out commit: " + file);
  }
  return { available: true, contract };
}

export function applicationEnvironment(contract, environment = process.env) {
  for (const name of ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]) {
    assert.ok(environment[name], "Missing isolated CI database field: " + name);
  }
  assert.equal(environment.PGHOST, "127.0.0.1", "CI database must be local");
  assert.equal(environment.PGDATABASE, "fatwa_ci", "Only isolated CI database is allowed");
  assert.equal(environment.PGUSER, "fatwa_ci", "Bootstrap role must not run application tests");
  const fields = {
    host: environment.PGHOST, port: environment.PGPORT, name: environment.PGDATABASE,
    user: environment.PGUSER, password: environment.PGPASSWORD,
  };
  fields.url = "postgresql://" + encodeURIComponent(fields.user) + ":" +
    encodeURIComponent(fields.password) + "@" + fields.host + ":" + fields.port + "/" + fields.name;
  const env = { ...environment, DJANGO_SETTINGS_MODULE: contract.settings_module };
  for (const [name, field] of Object.entries(contract.database_env)) env[name] = fields[field];
  return env;
}

// This check runs after S0 installation and before any application checks/tests.
// It refuses SQLite and a database/role that does not match the disposable CI service.
export const databaseProbe = [
  "import django",
  "from django.conf import settings",
  "from django.db import connection",
  "django.setup()",
  "assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'",
  "connection.ensure_connection()",
  "cursor = connection.cursor()",
  "cursor.execute('SELECT current_database(), current_user, rolsuper, rolcreaterole, rolreplication, rolbypassrls, rolcreatedb FROM pg_roles WHERE rolname = current_user')",
  "assert cursor.fetchone() == ('fatwa_ci', 'fatwa_ci', False, False, False, False, True)",
  "cursor.execute('SHOW server_version')",
  "print('Actual PostgreSQL server version:', cursor.fetchone()[0])",
  "connection.close()",
].join("\n");

export async function runStage(stage, detection, run = runCommand, environment = process.env) {
  assert.ok(detection.available, "Application checks are NOT_RUN until S0 integration");
  const env = applicationEnvironment(detection.contract, environment);
  if (stage === "database") {
    return run("python", ["-c", databaseProbe], { cwd: repoDir, env });
  }
  if (stage === "audit") {
    return run("python", ["-m", "pip_audit", "--local", "--progress-spinner", "off"], { cwd: repoDir, env });
  }
  assert.ok(stages.includes(stage), "Unknown application stage");
  const results = [];
  for (const args of detection.contract.commands[stage]) {
    results.push(run(args[0], args.slice(1), { cwd: repoDir, env }));
  }
  return results.filter(Boolean).join("\n");
}

async function main() {
  const stage = process.argv[2];
  const detection = await detectApplication();
  if (stage === "detect") {
    const message = detection.available
      ? "S0 committed integration contract found; application jobs must run."
      : "NOT_RUN: application lint/format/type/system/migration/PostgreSQL tests/dependency audit — " + detection.reason;
    console.log(message);
    if (process.env.GITHUB_OUTPUT) {
      await fs.appendFile(process.env.GITHUB_OUTPUT, "application=" + detection.available + "\n");
    }
    if (process.env.GITHUB_STEP_SUMMARY) {
      await fs.appendFile(process.env.GITHUB_STEP_SUMMARY, message + "\n\nNON_PRODUCTION_DRAFT / NOT_DEPLOYED / GATES_HOLD\n");
    }
    return;
  }
  console.log(await runStage(stage, detection));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error("FAIL: " + error.message); process.exitCode = 1; });
}
