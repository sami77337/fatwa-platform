import assert from "node:assert/strict";
import test from "node:test";
import { randomBytes } from "node:crypto";
import * as fs from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import {
  baseDir, parseMajor, parsePort, assertLocalEndpoint, validateCompose,
  loadCompose, prepare, preflight, composeArgs, createSmokePlan, smokeArgs, runSmoke,
} from "../dev.mjs";
import {
  validateContract, detectApplication, applicationEnvironment, runStage, safeRelative,
} from "../application.mjs";
import { checkRepository, validateWorkflow, validateInitScript } from "../checks.mjs";

async function fixture(callback) {
  const local = path.join(baseDir, ".local");
  await fs.mkdir(local, { recursive: true });
  const temp = await fs.mkdtemp(path.join(local, "test-"));
  try { return await callback(temp); }
  finally {
    // Resolve and check the absolute target before recursive deletion on Windows.
    const absolute = await fs.realpath(temp);
    const allowed = await fs.realpath(local);
    assert.ok(absolute.startsWith(allowed + path.sep) && path.basename(absolute).startsWith("test-"));
    await fs.rm(absolute, { recursive: true, force: true });
  }
}

async function copyInputs(temp) {
  for (const file of ["compose.pg18.yaml", "compose.pg17.yaml", ".env.example", "smoke.sh"]) {
    await fs.copyFile(path.join(baseDir, file), path.join(temp, file));
  }
}

async function activeContract() {
  const contract = JSON.parse(await fs.readFile(path.join(baseDir, "application-contract.example.json"), "utf8"));
  contract.status = "S0_COMMITTED_COMMANDS_CONFIRMED";
  contract.settings_module = "config.settings.test";
  contract.dependency_files = ["requirements.txt"];
  contract.commands.install = [["python", "-m", "pip", "install", "--requirement", "requirements.txt"]];
  return contract;
}

test("repository infrastructure and workflow boundary validation", async () => {
  await checkRepository();
});

for (const major of [18, 17]) {
  test("PostgreSQL " + major + " rejects exposure, trust auth, privileged containers, and foreign volumes", async () => {
    const original = await loadCompose(major);
    const mutations = [
      c => { c.services.postgres.ports[0].host_ip = "0.0.0.0"; },
      c => { c.services.postgres.environment.POSTGRES_HOST_AUTH_METHOD = "trust"; },
      c => { c.services.postgres.privileged = true; },
      c => { c.services.postgres.network_mode = "host"; },
      c => { c.networks.local.internal = false; },
      c => { c.volumes["pgdata" + major].external = true; },
      c => { c.volumes["pgdata" + major].name = "existing-user-volume"; },
      c => { c.services.postgres.volumes.push({ type: "bind", source: "/", target: "/host" }); },
      c => { c.services.worker = { image: "rabbitmq" }; },
      c => { c.services.postgres.environment.POSTGRES_PASSWORD = randomBytes(32).toString("hex"); },
      c => { c.services.postgres.image = "postgres:latest"; },
    ];
    for (const mutate of mutations) {
      const config = structuredClone(original);
      mutate(config);
      assert.throws(() => validateCompose(config, major));
    }
  });
}

test("separate PostgreSQL 18 and 17 persistence targets and project names", async () => {
  const primary = await loadCompose(18);
  const fallback = await loadCompose(17);
  assert.notEqual(primary.name, fallback.name);
  assert.notEqual(primary.services.postgres.volumes[0].source, fallback.services.postgres.volumes[0].source);
  assert.equal(primary.services.postgres.volumes[0].target, "/var/lib/postgresql");
  assert.equal(fallback.services.postgres.volumes[0].target, "/var/lib/postgresql/data");
});

test("reject unsupported major, privileged ports, extra env settings, and shell content", () => {
  assert.equal(parseMajor(), 18);
  assert.equal(parseMajor("17"), 17);
  for (const value of ["16", "19", "../17", "18;echo unsafe"]) assert.throws(() => parseMajor(value));
  assert.equal(parsePort("# comment\nFATWA_DEV_PORT=55432\n"), "55432");
  for (const text of ["FATWA_DEV_PORT=543\n", "FATWA_DEV_PORT=65536\n",
    "FATWA_DEV_PORT=55432\nPOSTGRES_HOST_AUTH_METHOD=trust\n", "FATWA_DEV_PORT=$(echo unsafe)\n"]) {
    assert.throws(() => parsePort(text));
  }
});

test("Docker endpoint guard refuses remote engines before any daemon operation", () => {
  assertLocalEndpoint("unix:///var/run/docker.sock");
  assertLocalEndpoint("npipe:////./pipe/docker_engine");
  for (const endpoint of ["tcp://127.0.0.1:2375", "ssh://host", "tcp://remote:2376", "npipe:////remote-server/pipe/docker_engine", ""]) {
    assert.throws(() => assertLocalEndpoint(endpoint));
  }
  let calls = 0;
  assert.throws(() => preflight(() => { calls += 1; }, { DOCKER_HOST: "ssh://remote" }));
  assert.equal(calls, 0);
});

test("preflight resolves local context and supports standalone Compose without shell parsing", () => {
  const calls = [];
  const runtime = preflight((cmd, args, options) => {
    calls.push({ cmd, args, options });
    if (args[0] === "context") return "npipe:////./pipe/docker_engine";
    if (args[0] === "info") return "29.6.1";
    return "5.1.4";
  }, { FATWA_COMPOSE_EXE: "C:/Program Files/Docker/compose.exe", DOCKER_CONTEXT: "desktop-linux" });
  assert.equal(runtime.command, "C:/Program Files/Docker/compose.exe");
  assert.equal(calls.length, 3);
  assert.equal(runtime.env.DOCKER_CONTEXT, undefined);
  assert.equal(runtime.env.DOCKER_HOST, "npipe:////./pipe/docker_engine");
});

test("prepare refuses overwriting existing env and partially prepared credentials", async () => {
  await fixture(async temp => {
    await copyInputs(temp);
    await fs.writeFile(path.join(temp, ".env"), "owner-existing-content");
    await assert.rejects(() => prepare(temp), /Refusing to overwrite/);
    assert.equal(await fs.readFile(path.join(temp, ".env"), "utf8"), "owner-existing-content");
    await fs.unlink(path.join(temp, ".env"));
    await fs.mkdir(path.join(temp, ".local"));
    await fs.writeFile(path.join(temp, ".local/app-password"), "synthetic-owner-value");
    await assert.rejects(() => prepare(temp), /Refusing to overwrite/);
    await assert.rejects(() => fs.access(path.join(temp, ".env")), { code: "ENOENT" });
  });
});

test("prepare creates only ignored credential files and does not replace them", async () => {
  await fixture(async temp => {
    await copyInputs(temp);
    await prepare(temp);
    const before = await fs.readFile(path.join(temp, ".local/app-password"), "utf8");
    assert.match(before, /^[a-f0-9]{64}\n$/);
    const bootstrap = await fs.readFile(path.join(temp, ".local/bootstrap-password"), "utf8");
    assert.notEqual(before, bootstrap);
    await assert.rejects(() => prepare(temp), /Refusing to overwrite/);
    assert.equal(await fs.readFile(path.join(temp, ".local/app-password"), "utf8"), before);
  });
});

test("git ignores local credentials and smoke output but includes the example env", () => {
  const result = spawnSync("git", ["check-ignore", "--no-index", "--stdin"], {
    cwd: path.resolve(baseDir, "../.."), encoding: "utf8", windowsHide: true,
    input: "infra/dev/.env\ninfra/dev/.local/app-password\ninfra/dev/.local/smoke-abc/compose.yaml\ninfra/dev/.env.example\n",
  });
  assert.equal(result.status, 0, result.stderr);
  const ignored = result.stdout.trim().split(/\r?\n/);
  assert.equal(ignored.length, 3);
  assert.ok(!ignored.includes("infra/dev/.env.example"));
});

test("development teardown command is namespaced; the CLI has no general volume-delete option", async () => {
  const args = composeArgs(18, baseDir);
  assert.equal(args[1], "fatwa-s5-dev-pg18");
  assert.ok(args.includes("--project-directory"));
  const result = spawnSync(process.execPath, [path.join(baseDir, "dev.mjs"), "reset"], {
    encoding: "utf8", windowsHide: true,
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Unknown command/);
});

test("smoke uses a fresh project with no ports and cleans up that project on verification failure", async () => {
  await fixture(async temp => {
    await copyInputs(temp);
    const plan = await createSmokePlan(18, temp);
    assert.deepEqual(plan.config.services.postgres.ports, []);
    assert.ok(!plan.project.startsWith("fatwa-s5-dev"));
    const calls = [];
    await assert.rejects(() => runSmoke(plan, { command: "docker", prefix: ["compose"], env: {} },
      (cmd, args) => {
        calls.push(args);
        if (args.at(-1) === "prepare") throw new Error("synthetic simulated restore failure");
        return "";
      }), /synthetic simulated restore failure/);
    const down = calls.find(args => args.includes("down"));
    assert.ok(down.includes("--volumes"));
    assert.ok(down.includes(plan.project));
    assert.ok(!calls.some(args => args.includes("prune")));
    await assert.rejects(() => fs.access(plan.temp), { code: "ENOENT" });
  });
});

test("smoke cleanup refuses a development project, external volume, or forged label", async () => {
  await fixture(async temp => {
    await copyInputs(temp);
    const plan = await createSmokePlan(17, temp);
    assert.throws(() => smokeArgs({ ...plan, project: "fatwa-s5-dev-pg17" }));
    const modified = structuredClone(plan);
    modified.config.volumes.pgdata17.external = true;
    assert.throws(() => smokeArgs(modified));
    const forged = structuredClone(plan);
    forged.config.services.postgres.labels["org.fatwa.smoke-project"] = "other";
    assert.throws(() => smokeArgs(forged));
  });
});

test("smoke verifies records after forcing container recreation", async () => {
  await fixture(async temp => {
    await copyInputs(temp);
    const plan = await createSmokePlan(17, temp);
    const calls = [];
    await runSmoke(plan, { command: "docker", prefix: ["compose"], env: {} }, (cmd, args) => {
      calls.push(args);
      return "";
    });
    const recreate = calls.findIndex(args => args.includes("--force-recreate"));
    const verify = calls.findIndex(args => args.at(-1) === "verify");
    assert.ok(recreate > 0 && verify > recreate);
    assert.ok(calls.at(-1).includes("down"));
  });
});

test("pre-S0 detection explicitly returns unavailable; app-present/contract-missing fails closed", async () => {
  await fixture(async temp => {
    const missing = await detectApplication(temp);
    assert.equal(missing.available, false);
    await assert.rejects(() => runStage("tests", missing), /NOT_RUN/);
    await fs.writeFile(path.join(temp, "manage.py"), "# synthetic file, not S0 code\n");
    await assert.rejects(() => detectApplication(temp), /integration contract is missing/);
  });
});

test("the example contract cannot activate CI and active contracts require committed input", async () => {
  const example = JSON.parse(await fs.readFile(path.join(baseDir, "application-contract.example.json"), "utf8"));
  assert.throws(() => validateContract(example));
  await fixture(async temp => {
    const contract = await activeContract();
    await fs.mkdir(path.join(temp, "infra/dev"), { recursive: true });
    await fs.writeFile(path.join(temp, "manage.py"), "# synthetic\n");
    await fs.writeFile(path.join(temp, "infra/dev/application-contract.json"), JSON.stringify(contract));
    await assert.rejects(() => detectApplication(temp, () => false), /checked-out commit/);
    assert.equal((await detectApplication(temp, () => true)).available, true);
  });
});

test("contract rejects traversal, shell executables, writable format, and writable migration stages", async () => {
  for (const value of ["../outside", "/outside", "C:\\outside", "-requirements.txt"]) {
    assert.throws(() => safeRelative(value));
  }
  const original = await activeContract();
  const mutations = [
    c => { c.commands.install[0][0] = "powershell"; },
    c => { c.commands.format[0] = ["python", "-m", "ruff", "format", "."]; },
    c => { c.commands.migration[0] = ["python", "manage.py", "migrate"]; },
    c => { c.commands.migration[0] = ["python", "manage.py", "makemigrations", "--check"]; },
    c => { c.database_env.PATH = "host"; },
    c => { c.dependency_files = ["../requirements.txt"]; },
    c => { c.commands.tests[0] = ["python", "manage.py", "createsuperuser"]; },
  ];
  for (const mutate of mutations) {
    const contract = structuredClone(original);
    mutate(contract);
    assert.throws(() => validateContract(contract));
  }
});

test("application checks bind to the disposable CI database and never bootstrap credentials", async () => {
  const contract = await activeContract();
  const environment = {
    PGHOST: "127.0.0.1", PGPORT: "5432", PGDATABASE: "fatwa_ci", PGUSER: "fatwa_ci",
    PGPASSWORD: randomBytes(32).toString("hex"),
  };
  const env = applicationEnvironment(contract, environment);
  assert.equal(env.DJANGO_SETTINGS_MODULE, "config.settings.test");
  assert.ok(env.DATABASE_URL.endsWith("@127.0.0.1:5432/fatwa_ci"));
  for (const change of [
    { PGHOST: "remote" }, { PGUSER: "fatwa_bootstrap" }, { PGDATABASE: "owner-data" },
  ]) {
    assert.throws(() => applicationEnvironment(contract, { ...environment, ...change }));
  }
  const calls = [];
  await runStage("tests", { available: true, contract }, (cmd, args, options) => {
    calls.push({ cmd, args, options }); return "synthetic mocked application command";
  }, environment);
  assert.equal(calls[0].cmd, "python");
  assert.equal(calls[0].args[0], "manage.py");
  assert.equal(calls[0].options.shell, undefined);
});

test("workflow rejects write permissions, unpinned actions, unsafe triggers, and unguarded app checks", async () => {
  const workflow = JSON.parse(await fs.readFile(path.resolve(baseDir, "../../.github/workflows/s5-ci.yml"), "utf8"));
  const mutations = [
    w => { w.permissions.contents = "write"; },
    w => { w.on.pull_request_target = {}; },
    w => { w.jobs.infra.steps[0].uses = "actions/checkout@main"; },
    w => { w.jobs.infra.steps[0].with["persist-credentials"] = true; },
    w => { w.jobs.application.if = "always()"; },
    w => { w.jobs.infra.steps.push({ run: "git push" }); },
  ];
  for (const mutate of mutations) {
    const candidate = structuredClone(workflow);
    mutate(candidate);
    assert.throws(() => validateWorkflow(candidate));
  }
});

test("prepare refuses a symlinked local directory before writing any credential file", async () => {
  await fixture(async temp => {
    await copyInputs(temp);
    const target = path.join(temp, "unrelated");
    await fs.mkdir(target);
    await fs.symlink(target, path.join(temp, ".local"), process.platform === "win32" ? "junction" : "dir");
    await assert.rejects(() => prepare(temp), /never a symlink/);
    assert.deepEqual(await fs.readdir(target), []);
  });
});

test("smoke cleanup errors preserve the verification failure and generated files for diagnosis", async () => {
  await fixture(async temp => {
    await copyInputs(temp);
    const plan = await createSmokePlan(18, temp);
    await assert.rejects(() => runSmoke(plan, { command: "docker", prefix: ["compose"], env: {} },
      (cmd, args) => {
        if (args.at(-1) === "prepare") throw new Error("simulated restore error");
        if (args.includes("down")) throw new Error("simulated daemon cleanup error");
        return "";
      }), /simulated restore error[\s\S]*Smoke cleanup failed/);
    await fs.access(plan.file);
  });
});

test("preflight refuses an old Docker daemon before publishing a loopback port", () => {
  const calls = [];
  assert.throws(() => preflight((cmd, args) => { calls.push(args); return "27.5.0"; },
    { DOCKER_HOST: "unix:///var/run/docker.sock" }), /Docker Engine 28/);
  assert.equal(calls.length, 1);
});

test("SQL validation requires a quoted psql binding and denies literals, interpolation, or elevated grants", async () => {
  const original = await fs.readFile(path.join(baseDir, "initdb/10-app.sh"), "utf8");
  validateInitScript(original);
  const mutations = [
    text => text.replace("PASSWORD :'app_password'", "PASSWORD=" + JSON.stringify(randomBytes(32).toString("hex"))),
    text => text.replace("PASSWORD :'app_password'", "PASSWORD '" + randomBytes(32).toString("hex") + "'"),
    text => text.replace("PASSWORD :'app_password'", "PASSWORD :app_password"),
    text => text.replace("<<'SQL'", "<<SQL"),
    text => text.replace("\\getenv app_password FATWA_INIT_APP_PASSWORD", ""),
    text => text.replace("NOSUPERUSER", "SUPERUSER"),
    text => text.replace("NOCREATEDB", "CREATEDB"),
    text => text.replace("NOCREATEROLE", "CREATEROLE"),
    text => text.replace("NOREPLICATION", "REPLICATION"),
    text => text.replace("NOBYPASSRLS", "BYPASSRLS"),
    text => text.replace("GRANT USAGE, CREATE", "GRANT ALL"),
    text => text.replace("set -eu", "set -eux"),
    text => text.replace("unset FATWA_INIT_APP_PASSWORD", ""),
  ];
  for (const mutate of mutations) assert.throws(() => validateInitScript(mutate(original)));
});

test("workflow keeps CI credential values entirely derived from runtime run identifiers", async () => {
  const workflow = JSON.parse(await fs.readFile(path.resolve(baseDir, "../../.github/workflows/s5-ci.yml"), "utf8"));
  const app = workflow.jobs.application;
  const fixture = "$" + "{{ github.run_id }}-" + "$" + "{{ github.run_attempt }}";
  assert.equal(app.env.PGPASSWORD, fixture);
  assert.equal(app.services.postgres.env.POSTGRES_PASSWORD, fixture);
});

test("container credential reads use mounted files, reject empty values, and never trace secrets", async () => {
  for (const script of ["healthcheck.sh", "smoke.sh"]) {
    const source = await fs.readFile(path.join(baseDir, script), "utf8");
    assert.match(source, /^PGPASSWORD="\$\(cat \/run\/secrets\/app_password\)"$/m);
    assert.match(source, /^\[ -n "\$PGPASSWORD" \]/m);
    assert.match(source, /^export PGPASSWORD$/m);
    assert.ok(!/set\s+-[a-z]*x/.test(source));
    assert.ok(!source.includes("\r"));
  }
});
