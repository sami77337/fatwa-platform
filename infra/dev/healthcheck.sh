#!/bin/sh
set -eu
PGPASSWORD="$(cat /run/secrets/app_password)"
[ -n "$PGPASSWORD" ] || { echo "Empty app password" >&2; exit 1; }
export PGPASSWORD
# TCP is essential: the entrypoint temporary server listens only on a socket.
result="$(psql -X -h 127.0.0.1 -U fatwa_app -d fatwa_reference -At --set ON_ERROR_STOP=1 -c "SELECT current_user = 'fatwa_app' AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls FROM pg_roles WHERE rolname = current_user")"
[ "$result" = t ]
