#!/usr/bin/env bash
# Creates the off-chain store, in the main database and in its "_test" twin:
#
#   transactional schema <- owned by TRANSACTIONAL_DB_USER
#
# Personal data (patients, prescription documents) lives only here, never
# on-chain. The app user owns its schema and nothing else.
#
# Runs on an empty volume; idempotent, so `just db-init` can re-run it.
set -euo pipefail

admin_psql() {
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" "$@"
}

admin_psql --dbname "$POSTGRES_DB" \
    -v tx_user="$TRANSACTIONAL_DB_USER" -v tx_password="$TRANSACTIONAL_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'tx_user', :'tx_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'tx_user') \gexec
ALTER ROLE :"tx_user" SET search_path = transactional;
SQL

for db in "$POSTGRES_DB" "${POSTGRES_DB}_test"; do
    admin_psql --dbname "$POSTGRES_DB" -v db="$db" <<'SQL'
SELECT format('CREATE DATABASE %I', :'db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db') \gexec
SQL
    admin_psql --dbname "$db" -v db="$db" -v tx_user="$TRANSACTIONAL_DB_USER" <<'SQL'
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"tx_user";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS transactional AUTHORIZATION :"tx_user";
SQL
done
