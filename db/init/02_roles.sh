#!/bin/bash
# Cria o usuario somente-leitura usado pela API.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE censo_api LOGIN PASSWORD '${API_DB_PASSWORD}';
    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO censo_api;
    GRANT USAGE ON SCHEMA public TO censo_api;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO censo_api;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO censo_api;
EOSQL
