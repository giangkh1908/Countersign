GRANT CONNECT ON DATABASE gateway TO gw_owner, gw_app, gw_report;
GRANT USAGE ON SCHEMA public TO gw_app, gw_report;
-- TODO(M1): quyền theo bảng (gw_app: INSERT,SELECT audit_log/usage_events; SELECT,INSERT,UPDATE api_keys;
-- gw_report: SELECT usage_events/departments) do migration Alembic cấp; init chỉ lo role/extension.
