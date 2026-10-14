#!/bin/sh
set -eu
# The official entrypoint supplies the bootstrap role through a local socket.
# Import the password through the environment; do not put it in argv or logs.
FATWA_INIT_APP_PASSWORD="$(cat /run/secrets/app_password)"
[ -n "$FATWA_INIT_APP_PASSWORD" ] || { echo "Empty app password" >&2; exit 1; }
export FATWA_INIT_APP_PASSWORD
psql -X --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password FATWA_INIT_APP_PASSWORD
CREATE ROLE fatwa_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE DATABASE fatwa_reference OWNER fatwa_app;
REVOKE ALL ON DATABASE fatwa_reference FROM PUBLIC;
\connect fatwa_reference
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO fatwa_app;
ALTER DEFAULT PRIVILEGES FOR ROLE fatwa_app REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
SQL
unset FATWA_INIT_APP_PASSWORD
