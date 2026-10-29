GRANT CONNECT ON DATABASE tickets TO tk_owner, tk_app, mcp_audit_w;
GRANT USAGE ON SCHEMA public TO tk_app, mcp_audit_w;
-- TODO(M1): tk_app DML trên tickets*, RLS FORCE: do migration Alembic.
