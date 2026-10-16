#!/bin/bash
# Creates the read-only role used by the LLM API.
# It can SELECT from the v_* views only. It cannot read base tables
# (names, NIC, phone, email, MRN, DOB) and cannot write anything.
set -e

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v reader_pw="$LLM_READER_PASSWORD" <<'EOSQL'
CREATE ROLE llm_reader LOGIN PASSWORD :'reader_pw';
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM llm_reader;
GRANT CONNECT ON DATABASE hospital TO llm_reader;
GRANT USAGE ON SCHEMA public TO llm_reader;
GRANT SELECT ON v_patients, v_doctors, v_appointments, v_diagnoses, v_clinical_notes TO llm_reader;
ALTER ROLE llm_reader SET default_transaction_read_only = on;
ALTER ROLE llm_reader SET statement_timeout = '5s';
EOSQL

echo "llm_reader role created (read-only, views only)."
