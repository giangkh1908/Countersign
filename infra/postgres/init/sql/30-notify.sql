-- notify (actions-roles.md §3). Chạy bằng `postgres` trên DB notify; idempotent.
-- report_deliveries là sổ "đã gửi chưa" của notify-mcp: một intent tối đa một dòng (UNIQUE) nên
-- không bao giờ gửi hai lần. Không lưu nội dung tin, chỉ SHA-256 của nó.
CREATE SCHEMA IF NOT EXISTS acme AUTHORIZATION nt_owner;
GRANT CONNECT ON DATABASE notify TO nt_owner, nt_app, mcp_audit_w;
GRANT USAGE ON SCHEMA public TO nt_app, mcp_audit_w;
GRANT USAGE ON SCHEMA acme TO nt_app;

SET ROLE nt_owner;

CREATE TABLE IF NOT EXISTS report_deliveries (
  id bigserial PRIMARY KEY,
  intent_id uuid UNIQUE NOT NULL,                      -- UNIQUE: mỗi intent tối đa một lần gửi
  channel text NOT NULL,                               -- bí danh kênh, không phải chat ID
  text_sha256 char(64) NOT NULL,
  actor_sub text NOT NULL,
  approval_jti uuid NOT NULL,
  status text NOT NULL CHECK (status IN ('sending', 'sent', 'unknown', 'failed')),
  detail text NOT NULL DEFAULT '',                     -- mã lỗi/kind ngắn, không chứa token hay nội dung
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS report_deliveries_actor_idx ON report_deliveries (actor_sub, created_at);

-- Chỉ chuyển trạng thái từ `sending`; `sent|unknown|failed` là cuối. Chỉ đổi status/detail/updated_at.
CREATE OR REPLACE FUNCTION acme.delivery_guard() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF OLD.status <> 'sending' THEN
    RAISE EXCEPTION 'report_deliveries: % is final', OLD.status USING ERRCODE = '42501';
  END IF;
  IF NEW.intent_id <> OLD.intent_id OR NEW.channel <> OLD.channel OR NEW.text_sha256 <> OLD.text_sha256
     OR NEW.actor_sub <> OLD.actor_sub OR NEW.approval_jti <> OLD.approval_jti THEN
    RAISE EXCEPTION 'report_deliveries: immutable columns' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS report_deliveries_guard ON report_deliveries;
CREATE TRIGGER report_deliveries_guard BEFORE UPDATE ON report_deliveries
  FOR EACH ROW EXECUTE FUNCTION acme.delivery_guard();

-- tool_audit (contracts §5): ghi bởi mcp_audit_w
CREATE SEQUENCE IF NOT EXISTS tool_audit_id_seq;
CREATE TABLE IF NOT EXISTS tool_audit (
  id bigint PRIMARY KEY DEFAULT nextval('tool_audit_id_seq'),
  ts timestamptz NOT NULL,
  request_id uuid, actor_type text NOT NULL, actor_id text NOT NULL, end_user_sub text,
  action text NOT NULL, resource text, decision text NOT NULL CHECK (decision IN ('allow','deny','error')),
  details jsonb NOT NULL DEFAULT '{}',
  intent_id uuid NULL,
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
CREATE INDEX IF NOT EXISTS tool_audit_intent_idx ON tool_audit (intent_id) WHERE intent_id IS NOT NULL;

-- Quyền (least privilege): nt_app không DELETE, không DDL, chỉ UPDATE ba cột trạng thái
REVOKE ALL ON report_deliveries, tool_audit FROM PUBLIC, nt_app, mcp_audit_w;
GRANT SELECT, INSERT ON report_deliveries TO nt_app;
GRANT UPDATE (status, detail, updated_at) ON report_deliveries TO nt_app;
GRANT INSERT, SELECT ON tool_audit TO mcp_audit_w;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nt_app;
GRANT USAGE ON SEQUENCE tool_audit_id_seq TO mcp_audit_w;

RESET ROLE;
