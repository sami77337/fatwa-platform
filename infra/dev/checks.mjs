import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { baseDir, loadCompose } from "./dev.mjs";

export function validateWorkflow(workflow) {
  assert.deepEqual(workflow.permissions, { contents: "read" });
  assert.equal(workflow.on.pull_request_target, undefined);
  assert.ok(workflow.on.pull_request.paths.includes("infra/dev/**"));
  assert.ok(workflow.on.pull_request.paths.includes("manage.py"));
  assert.deepEqual(workflow.on.push.branches, ["codex/s5-infra-ci-20261013"]);
  const jobs = workflow.jobs;
  assert.deepEqual(Object.keys(jobs).sort(), ["application", "infra", "postgres-smoke"]);
  assert.deepEqual(jobs["postgres-smoke"].strategy.matrix.major, [18, 17]);
  assert.equal(jobs.application.if, "needs.infra.outputs.application == 'true'");
  assert.equal(jobs.infra.outputs.application, "$" + "{{ steps.detect.outputs.application }}");
  assert.deepEqual(jobs.application.strategy.matrix.postgres, ["18.6-bookworm", "17.11-bookworm"]);
  assert.deepEqual(jobs.application.services.postgres.ports, ["127.0.0.1:5432:5432"]);
  assert.equal(jobs.application.services.postgres.env.POSTGRES_HOST_AUTH_METHOD, "scram-sha-256");
  const stageCommands = [
    "install", "database", "lint", "format", "type", "system", "migration", "tests", "audit",
  ].map(stage => "node infra/dev/application.mjs " + stage);
  for (const command of stageCommands) {
    assert.ok(jobs.application.steps.some(step => step.run === command), "Missing application stage: " + command);
  }
  assert.ok(jobs.application.steps.some(step =>
    step.uses?.startsWith("actions/setup-python@") && step.with["python-version"] === "3.13"));
  assert.ok(jobs.infra.steps.some(step => step.id === "detect" && step.run === "node infra/dev/application.mjs detect"));
  for (const job of Object.values(jobs)) {
    assert.equal(job["runs-on"], "ubuntu-24.04");
    assert.ok(job["timeout-minutes"] > 0);
    for (const step of job.steps) {
      if (step.uses) {
        assert.match(step.uses, /^actions\/(checkout|setup-node|setup-python)@[a-f0-9]{40}$/);
        if (step.uses.startsWith("actions/checkout@")) {
          assert.equal(step.with["persist-credentials"], false);
        }
      }
      if (step.run) {
        assert.ok(!/\b(deploy|kubectl|terraform|gh\s+pr|git\s+(push|commit))\b/.test(step.run));
      }
    }
  }
  assert.ok(!JSON.stringify(workflow).includes("secrets."));
  return workflow;
}

export function validateInitScript(init) {
  assert.ok(!init.includes("\r"), "Container shell scripts must have LF endings");
  assert.match(init, /^set -eu$/m);
  assert.match(init, /^FATWA_INIT_APP_PASSWORD="\$\(cat \/run\/secrets\/app_password\)"$/m);
  assert.match(init, /^\[ -n "\$FATWA_INIT_APP_PASSWORD" \]/m);
  assert.match(init, /^export FATWA_INIT_APP_PASSWORD$/m);
  assert.match(init, /psql -X --username "\$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'/);
  assert.match(init, /^\\getenv app_password FATWA_INIT_APP_PASSWORD$/m);
  assert.match(init, /^CREATE ROLE fatwa_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;$/m);
  assert.match(init, /^REVOKE ALL ON DATABASE fatwa_reference FROM PUBLIC;$/m);
  assert.match(init, /^REVOKE CREATE ON SCHEMA public FROM PUBLIC;$/m);
  assert.match(init, /^GRANT USAGE, CREATE ON SCHEMA public TO fatwa_app;$/m);
  assert.match(init, /^ALTER DEFAULT PRIVILEGES FOR ROLE fatwa_app REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;$/m);
  assert.match(init, /^unset FATWA_INIT_APP_PASSWORD$/m);
  assert.ok(!/\b(?:GRANT\s+ALL|SUPERUSER|CREATEDB|CREATEROLE|REPLICATION|BYPASSRLS)\b/i.test(init),
    "App role must remain restricted");
  assert.ok(!/set\s+-[a-z]*x|--(?:password|set|variable)[ =].*FATWA_INIT_APP_PASSWORD/.test(init),
    "Passwords must not be traced or placed in argv");
  return init;
}

export async function checkRepository(directory = baseDir) {
  for (const major of [18, 17]) await loadCompose(major, directory);
  const root = path.resolve(directory, "../..");
  validateWorkflow(JSON.parse(await fs.readFile(path.join(root, ".github/workflows/s5-ci.yml"), "utf8")));
  const ignore = await fs.readFile(path.join(directory, ".gitignore"), "utf8");
  for (const rule of [".env", ".env.*", "!.env.example", ".local/"]) {
    assert.ok(ignore.split(/\r?\n/).includes(rule), "Missing ignored credential/output rule: " + rule);
  }
  const init = await fs.readFile(path.join(directory, "initdb/10-app.sh"), "utf8");
  validateInitScript(init);
  for (const script of ["initdb/10-app.sh", "healthcheck.sh", "smoke.sh"]) {
    const content = await fs.readFile(path.join(directory, script), "utf8");
    assert.ok(!content.includes("\r"), "Container shell scripts must have LF endings: " + script);
    assert.ok(!/set\s+-[a-z]*x/.test(content), "Passwords must never be traced");
  }
  const health = await fs.readFile(path.join(directory, "healthcheck.sh"), "utf8");
  assert.match(health, /-h 127\.0\.0\.1 -U fatwa_app -d fatwa_reference/);
  const smoke = await fs.readFile(path.join(directory, "smoke.sh"), "utf8");
  for (const evidence of ["pg_dump", "pg_restore", "CREATE ROLE s5_forbidden", "CREATE DATABASE s5_forbidden", "SELECT rolpassword FROM pg_authid", "md5(string_agg"]) {
    assert.ok(smoke.includes(evidence), "Missing smoke verification: " + evidence);
  }
  const requirements = await fs.readFile(path.join(directory, "requirements-ci.txt"), "utf8");
  for (const line of requirements.split(/\r?\n/).filter(line => line && !line.startsWith("#"))) {
    assert.match(line, /^[a-z][a-z-]*==\d+\.\d+\.\d+$/);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  checkRepository().then(() => {
    console.log("PASS: Compose boundaries, CI JSON/YAML syntax and guards, ignored paths, SQL role defaults, pinned CI dependencies.");
  }).catch(error => { console.error("FAIL: " + error.message); process.exitCode = 1; });
}
