#!/bin/bash
# Cria o usuario somente-leitura usado pela API, com limites contra consultas abusivas.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE censo_api LOGIN PASSWORD '${API_DB_PASSWORD}' CONNECTION LIMIT 20;
    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO censo_api;
    GRANT USAGE ON SCHEMA public TO censo_api;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO censo_api;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO censo_api;
    -- Defesa em profundidade para a API publica:
    ALTER ROLE censo_api SET default_transaction_read_only = on;
    ALTER ROLE censo_api SET statement_timeout = '30s';
    ALTER ROLE censo_api SET idle_in_transaction_session_timeout = '30s';
    ALTER ROLE censo_api SET work_mem = '32MB';
EOSQL
