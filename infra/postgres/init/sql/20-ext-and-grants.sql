-- Chạy bằng `postgres` trên từng DB
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS unaccent;
