-- Mọi role: NOSUPERUSER NOBYPASSRLS NOREPLICATION; không role app nào là superuser/BYPASSRLS
CREATE ROLE gw_owner  LOGIN PASSWORD :'gw_owner_pw'  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE gw_app    LOGIN PASSWORD :'gw_app_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE gw_report LOGIN PASSWORD :'gw_report_pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;   -- Grafana
CREATE ROLE kn_owner  LOGIN PASSWORD :'kn_owner_pw'  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE kn_app    LOGIN PASSWORD :'kn_app_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE kn_ingest LOGIN PASSWORD :'kn_ingest_pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE tk_owner  LOGIN PASSWORD :'tk_owner_pw'  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE tk_app    LOGIN PASSWORD :'tk_app_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE an_owner  LOGIN PASSWORD :'an_owner_pw'  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE an_reader LOGIN PASSWORD :'an_reader_pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE ag_owner  LOGIN PASSWORD :'ag_owner_pw'  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;   -- chạy setup() của checkpointer
CREATE ROLE ag_app    LOGIN PASSWORD :'ag_app_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE mcp_audit_w LOGIN PASSWORD :'mcp_audit_pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;   -- chỉ INSERT/SELECT trên tool_audit (contracts §3.6)
CREATE ROLE kc_app    LOGIN PASSWORD :'kc_app_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE lf_app    LOGIN PASSWORD :'lf_app_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

CREATE DATABASE gateway   OWNER gw_owner;
CREATE DATABASE knowledge OWNER kn_owner;
CREATE DATABASE tickets   OWNER tk_owner;
CREATE DATABASE analytics OWNER an_owner;
CREATE DATABASE agent     OWNER ag_owner;      -- ag_app chỉ DML (GRANT sau khi setup())
CREATE DATABASE keycloak  OWNER kc_app;
CREATE DATABASE langfuse  OWNER lf_app;

-- Timeout & giới hạn theo role (contracts §3.4 cho an_reader)
ALTER ROLE gw_app    SET statement_timeout = '5s';   ALTER ROLE gw_app SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE gw_report SET statement_timeout = '10s';  ALTER ROLE gw_report SET default_transaction_read_only = on;
ALTER ROLE kn_app    SET statement_timeout = '3s';   ALTER ROLE kn_app SET default_transaction_read_only = on;
ALTER ROLE kn_ingest SET statement_timeout = '60s';
ALTER ROLE tk_app    SET statement_timeout = '3s';   ALTER ROLE tk_app SET idle_in_transaction_session_timeout = '5s';
ALTER ROLE an_reader SET statement_timeout = '3s';   ALTER ROLE an_reader SET idle_in_transaction_session_timeout = '5s';
ALTER ROLE an_reader SET default_transaction_read_only = on;   ALTER ROLE an_reader SET work_mem = '4MB';
ALTER ROLE an_reader SET search_path = public;
ALTER ROLE ag_app    SET statement_timeout = '10s';
ALTER ROLE gw_owner SET statement_timeout = '5min';  ALTER ROLE kn_owner SET statement_timeout = '5min';   -- migration
ALTER ROLE tk_owner SET statement_timeout = '5min';  ALTER ROLE an_owner SET statement_timeout = '5min';
ALTER ROLE gw_app CONNECTION LIMIT 50;  ALTER ROLE an_reader CONNECTION LIMIT 10;
ALTER ROLE kn_app CONNECTION LIMIT 20;  ALTER ROLE tk_app CONNECTION LIMIT 20;
