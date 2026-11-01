-- knowledge (contracts §5). Chạy bằng `postgres` trên DB knowledge; idempotent.
-- Phần cần superuser (extension) trước, rồi SET ROLE kn_owner để mọi đối tượng thuộc kn_owner.
CREATE EXTENSION IF NOT EXISTS vector;       -- Cần xác minh: pgvector có "trusted" ở bản pin không
CREATE SCHEMA IF NOT EXISTS acme AUTHORIZATION kn_owner;
CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA acme;

GRANT CONNECT ON DATABASE knowledge TO kn_owner, kn_app, kn_ingest, mcp_audit_w;
GRANT USAGE ON SCHEMA public TO kn_app, kn_ingest, mcp_audit_w;
GRANT USAGE ON SCHEMA acme TO kn_app, kn_ingest;

ALTER DEFAULT PRIVILEGES FOR ROLE kn_owner IN SCHEMA public GRANT SELECT ON TABLES TO kn_app;
ALTER DEFAULT PRIVILEGES FOR ROLE kn_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kn_ingest;
ALTER DEFAULT PRIVILEGES FOR ROLE kn_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO kn_ingest;

SET ROLE kn_owner;

-- unaccent() chỉ STABLE nên không hợp lệ trong cột GENERATED ... STORED -> hàm bọc IMMUTABLE
CREATE OR REPLACE FUNCTION acme.immutable_unaccent(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  AS $$ SELECT acme.unaccent('acme.unaccent'::regdictionary, $1) $$;

CREATE TABLE IF NOT EXISTS documents (
  id uuid PRIMARY KEY, title text NOT NULL, source_path text NOT NULL, sha256 char(64) NOT NULL,
  department text NOT NULL,              -- 'ALL' = toàn công ty
  classification smallint NOT NULL CHECK (classification BETWEEN 0 AND 3),   -- 0 public, 1 internal, 2 confidential, 3 secret
  allowed_roles text[] NOT NULL DEFAULT '{}',   -- rỗng = mọi role đạt classification
  owner_sub text, version int NOT NULL DEFAULT 1,
  ingested_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_dept_class_idx ON documents (department, classification);

CREATE TABLE IF NOT EXISTS chunks (
  id bigserial PRIMARY KEY, document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  ord int NOT NULL, heading text, content text NOT NULL, n_tokens int NOT NULL,
  department text NOT NULL, classification smallint NOT NULL CHECK (classification BETWEEN 0 AND 3),
  allowed_roles text[] NOT NULL,         -- denormalized để filter
  embedding vector(1024) NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', acme.immutable_unaccent(content))) STORED,
  UNIQUE (document_id, ord)
);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_dept_class_idx ON chunks (department, classification);

-- RLS (FORCE). Cast clearance an toàn: GUC rỗng/thiếu -> -1 -> không thấy gì.
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;    ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY; ALTER TABLE documents FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS chunk_acl ON chunks;
CREATE POLICY chunk_acl ON chunks FOR SELECT TO kn_app USING (
  (department = 'ALL' OR department = ANY (string_to_array(current_setting('app.depts', true), ',')))
  AND classification <= coalesce(nullif(current_setting('app.clearance', true),''),'-1')::int
  AND (cardinality(allowed_roles) = 0 OR allowed_roles && string_to_array(current_setting('app.roles', true), ','))
);
DROP POLICY IF EXISTS doc_acl ON documents;
CREATE POLICY doc_acl ON documents FOR SELECT TO kn_app USING (   -- cùng điều kiện như chunk_acl
  (department = 'ALL' OR department = ANY (string_to_array(current_setting('app.depts', true), ',')))
  AND classification <= coalesce(nullif(current_setting('app.clearance', true),''),'-1')::int
  AND (cardinality(allowed_roles) = 0 OR allowed_roles && string_to_array(current_setting('app.roles', true), ','))
);
-- Ingest: kn_ingest bị FORCE RLS chặn nếu thiếu policy
DROP POLICY IF EXISTS chunk_ingest ON chunks;
CREATE POLICY chunk_ingest ON chunks FOR ALL TO kn_ingest USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS doc_ingest ON documents;
CREATE POLICY doc_ingest ON documents FOR ALL TO kn_ingest USING (true) WITH CHECK (true);

-- tool_audit (contracts §5): hash-chain HMAC, chỉ INSERT/SELECT, trigger chặn UPDATE/DELETE/TRUNCATE.
CREATE SEQUENCE IF NOT EXISTS tool_audit_id_seq;
CREATE TABLE IF NOT EXISTS tool_audit (
  id bigint PRIMARY KEY DEFAULT nextval('tool_audit_id_seq'),   -- app lấy nextval TRƯỚC khi băm
  ts timestamptz NOT NULL,               -- app gán trước khi băm; KHÔNG DEFAULT now()
  request_id uuid, actor_type text NOT NULL, actor_id text NOT NULL, end_user_sub text,
  action text NOT NULL, resource text, decision text NOT NULL CHECK (decision IN ('allow','deny','error')),
  details jsonb NOT NULL DEFAULT '{}',
  intent_id uuid NULL,                   -- NULL với tool đọc
  hmac_kid smallint NOT NULL, prev_hash bytea NOT NULL, hash bytea NOT NULL
);
CREATE OR REPLACE FUNCTION acme.audit_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION '% on % is not allowed (append-only)', TG_OP, TG_TABLE_NAME USING ERRCODE = '42501'; END $$;
DROP TRIGGER IF EXISTS tool_audit_no_mod ON tool_audit;
CREATE TRIGGER tool_audit_no_mod BEFORE UPDATE OR DELETE ON tool_audit
  FOR EACH ROW EXECUTE FUNCTION acme.audit_immutable();
DROP TRIGGER IF EXISTS tool_audit_no_trunc ON tool_audit;
CREATE TRIGGER tool_audit_no_trunc BEFORE TRUNCATE ON tool_audit
  FOR EACH STATEMENT EXECUTE FUNCTION acme.audit_immutable();
CREATE INDEX IF NOT EXISTS tool_audit_ts_idx ON tool_audit (ts);
-- default privileges ở trên đã cấp cho kn_app/kn_ingest -> thu hồi, chỉ mcp_audit_w
REVOKE ALL ON tool_audit, tool_audit_id_seq FROM PUBLIC, kn_app, kn_ingest;
GRANT INSERT, SELECT ON tool_audit TO mcp_audit_w;
GRANT USAGE ON SEQUENCE tool_audit_id_seq TO mcp_audit_w;

RESET ROLE;
