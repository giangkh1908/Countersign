GRANT CONNECT ON DATABASE analytics TO an_owner, an_reader, mcp_audit_w;
GRANT USAGE ON SCHEMA public TO an_reader, mcp_audit_w;
-- TODO(M1): an_reader chỉ SELECT trên v_*, REVOKE ALL trên bảng gốc, schema acme cho verify_ctx(): migration Alembic.
