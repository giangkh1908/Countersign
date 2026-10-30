-- Chạy bằng `postgres` trên từng DB
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- unaccent: cài trong schema `acme` ở 30-knowledge.sql (contracts §3.2); không cài ở public.
