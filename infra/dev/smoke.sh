#!/bin/sh
set -eu
PGPASSWORD="$(cat /run/secrets/app_password)"
[ -n "$PGPASSWORD" ] || { echo "Empty app password" >&2; exit 1; }
export PGPASSWORD
query() { psql -X -h 127.0.0.1 -U fatwa_app -d "$1" -At --set ON_ERROR_STOP=1 -c "$2"; }
sh /opt/fatwa/healthcheck.sh
query fatwa_reference "SHOW server_version"
actual_major="$(query fatwa_reference "SELECT current_setting('server_version_num')::int / 10000")"
[ "$actual_major" = "$FATWA_EXPECTED_MAJOR" ]
if [ "${1:-}" = prepare ]; then
  query fatwa_reference "CREATE TABLE s5_synthetic (id integer PRIMARY KEY, title text NOT NULL); INSERT INTO s5_synthetic VALUES (1, 'S5 synthetic reference'), (2, 'عنوان اصطناعي لا يمثل نص مصدر');" >/dev/null
  for forbidden in "CREATE ROLE s5_forbidden" "CREATE DATABASE s5_forbidden" "SELECT rolpassword FROM pg_authid"; do
    if query fatwa_reference "$forbidden" >/dev/null 2>&1; then
      echo "FAIL: app role performed forbidden database operation" >&2; exit 1
    fi
  done
  pg_dump -h 127.0.0.1 -U fatwa_app -d fatwa_reference --format=custom --no-owner --file=/tmp/s5-synthetic.dump
  psql -X -U fatwa_bootstrap -d postgres --set ON_ERROR_STOP=1 -c "CREATE DATABASE fatwa_smoke_restore OWNER fatwa_app;" >/dev/null
  psql -X -U fatwa_bootstrap -d fatwa_smoke_restore --set ON_ERROR_STOP=1 -c "REVOKE ALL ON DATABASE fatwa_smoke_restore FROM PUBLIC; REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE, CREATE ON SCHEMA public TO fatwa_app;" >/dev/null
  pg_restore -h 127.0.0.1 -U fatwa_app -d fatwa_smoke_restore --no-owner --no-acl --exit-on-error /tmp/s5-synthetic.dump
elif [ "${1:-}" != verify ]; then
  echo "Usage: smoke.sh prepare|verify" >&2; exit 2
fi
original="$(query fatwa_reference "SELECT md5(string_agg(id::text || title, '|' ORDER BY id)) FROM s5_synthetic")"
restored="$(query fatwa_smoke_restore "SELECT md5(string_agg(id::text || title, '|' ORDER BY id)) FROM s5_synthetic")"
[ "$(query fatwa_reference 'SELECT count(*) FROM s5_synthetic')" = 2 ]
[ "$(query fatwa_smoke_restore 'SELECT count(*) FROM s5_synthetic')" = 2 ]
[ "$original" = "$restored" ]
printf 'PASS: PostgreSQL %s synthetic rows, restricted app role, backup/restore verified\n' "$actual_major"
