-- Idempotent: chạy lại không lỗi (role/DB đã có thì bỏ qua; mật khẩu luôn được đồng bộ lại từ secret).
-- Mọi role: NOSUPERUSER NOBYPASSRLS NOREPLICATION; không role app nào là superuser/BYPASSRLS
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION', r)
FROM (VALUES ('gw_owner'), ('gw_app'), ('gw_report'), ('kn_owner'), ('kn_app'), ('kn_ingest'), ('tk_owner'), ('tk_app'), ('nt_owner'), ('nt_app'), ('ag_owner'), ('ag_app'), ('mcp_audit_w'), ('kc_app')) AS v(r)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v.r) \gexec

SELECT format('ALTER ROLE %I PASSWORD %L', r, pw)
FROM (VALUES
  ('gw_owner', :'gw_owner_pw'),
  ('gw_app', :'gw_app_pw'),
  ('gw_report', :'gw_report_pw'),
  ('kn_owner', :'kn_owner_pw'),
  ('kn_app', :'kn_app_pw'),
  ('kn_ingest', :'kn_ingest_pw'),
  ('tk_owner', :'tk_owner_pw'),
  ('tk_app', :'tk_app_pw'),
  ('nt_owner', :'nt_owner_pw'),
  ('nt_app', :'nt_app_pw'),
  ('ag_owner', :'ag_owner_pw'),
  ('ag_app', :'ag_app_pw'),
  ('mcp_audit_w', :'mcp_audit_pw'),
  ('kc_app', :'kc_app_pw')
) AS v(r, pw) \gexec

SELECT format('CREATE DATABASE %I OWNER %I', d, o)
FROM (VALUES ('gateway', 'gw_owner'), ('knowledge', 'kn_owner'), ('tickets', 'tk_owner'), ('notify', 'nt_owner'), ('agent', 'ag_owner'), ('keycloak', 'kc_app')) AS v(d, o)
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = v.d) \gexec
-- ag_app chỉ DML; quyền cấp ở 30-agent.sql (default privileges cho bảng setup() tạo sau)



-- Timeout & giới hạn theo role
ALTER ROLE gw_app    SET statement_timeout = '5s';   ALTER ROLE gw_app SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE gw_report SET statement_timeout = '10s';  ALTER ROLE gw_report SET default_transaction_read_only = on;
ALTER ROLE kn_app    SET statement_timeout = '3s';   ALTER ROLE kn_app SET default_transaction_read_only = on;
ALTER ROLE kn_ingest SET statement_timeout = '60s';
ALTER ROLE tk_app    SET statement_timeout = '3s';   ALTER ROLE tk_app SET idle_in_transaction_session_timeout = '5s';
ALTER ROLE nt_app    SET statement_timeout = '3s';   ALTER ROLE nt_app SET idle_in_transaction_session_timeout = '5s';
ALTER ROLE nt_owner SET statement_timeout = '5min';  ALTER ROLE nt_app CONNECTION LIMIT 20;
ALTER ROLE ag_app    SET statement_timeout = '10s';
ALTER ROLE gw_owner SET statement_timeout = '5min';  ALTER ROLE kn_owner SET statement_timeout = '5min';   -- migration
ALTER ROLE tk_owner SET statement_timeout = '5min';
ALTER ROLE gw_app CONNECTION LIMIT 50;
ALTER ROLE kn_app CONNECTION LIMIT 20;  ALTER ROLE tk_app CONNECTION LIMIT 20;
