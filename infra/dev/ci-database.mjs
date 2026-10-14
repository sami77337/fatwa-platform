import assert from "node:assert/strict";
import { runCommand } from "./dev.mjs";

const container = process.env.FATWA_CI_CONTAINER;
assert.equal(process.env.CI, "true", "Provisioning is only for an ephemeral CI job");
assert.match(container || "", /^[a-f0-9]{12,64}$/, "Expected GitHub service container ID");
assert.equal(process.env.PGUSER, "fatwa_ci");
assert.equal(process.env.PGDATABASE, "fatwa_ci");
assert.ok(process.env.PGPASSWORD, "Disposable CI password missing");
const sql = [
  "\\getenv ci_password PGPASSWORD",
  "CREATE ROLE fatwa_ci LOGIN PASSWORD :'ci_password' NOSUPERUSER CREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;",
  "CREATE DATABASE fatwa_ci OWNER fatwa_ci;",
  "REVOKE ALL ON DATABASE fatwa_ci FROM PUBLIC;",
  "\\connect fatwa_ci",
  "REVOKE CREATE ON SCHEMA public FROM PUBLIC;",
  "GRANT USAGE, CREATE ON SCHEMA public TO fatwa_ci;",
].join("\n") + "\n";
console.log(runCommand("docker", [
  "exec", "-i", "--env", "PGPASSWORD", container,
  "psql", "-X", "-U", "fatwa_bootstrap", "-d", "postgres", "--set", "ON_ERROR_STOP=1",
], { input: sql }));
console.log("Provisioned disposable CI test role: NOSUPERUSER, NOCREATEROLE; CREATEDB for Django test databases only.");
