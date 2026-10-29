-- TODO spike M0 [cần xác minh]: pgvector có "trusted" ở bản pin không (hiện tạo bởi superuser).
CREATE EXTENSION IF NOT EXISTS vector;
GRANT CONNECT ON DATABASE knowledge TO kn_owner, kn_app, kn_ingest, mcp_audit_w;
GRANT USAGE ON SCHEMA public TO kn_app, kn_ingest, mcp_audit_w;
ALTER DEFAULT PRIVILEGES FOR ROLE kn_owner IN SCHEMA public GRANT SELECT ON TABLES TO kn_app;
ALTER DEFAULT PRIVILEGES FOR ROLE kn_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kn_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE kn_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO kn_ingest;
-- TODO(M1): quyền INSERT/SELECT của mcp_audit_w trên tool_audit đặt trong migration Alembic.
