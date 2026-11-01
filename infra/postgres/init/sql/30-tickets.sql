-- tickets (contracts §5). Chạy bằng `postgres` trên DB tickets; idempotent.
CREATE SCHEMA IF NOT EXISTS acme AUTHORIZATION tk_owner;
GRANT CONNECT ON DATABASE tickets TO tk_owner, tk_app, mcp_audit_w;
GRANT USAGE ON SCHEMA public TO tk_app, mcp_audit_w;
GRANT USAGE ON SCHEMA acme TO tk_app;

SET ROLE tk_owner;

-- Ngữ cảnh người gọi từ GUC do mcp đặt bằng SET LOCAL; thiếu -> rỗng -> không thấy gì.
CREATE OR REPLACE FUNCTION acme.ctx_sub() RETURNS text LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('app.sub', true), '') $$;
CREATE OR REPLACE FUNCTION acme.ctx_depts() RETURNS text[] LANGUAGE sql STABLE AS
  $$ SELECT coalesce(string_to_array(nullif(current_setting('app.depts', true), ''), ','), '{}'::text[]) $$;
CREATE OR REPLACE FUNCTION acme.ctx_roles() RETURNS text[] LANGUAGE sql STABLE AS
  $$ SELECT coalesce(string_to_array(nullif(current_setting('app.roles', true), ''), ','), '{}'::text[]) $$;

CREATE TABLE IF NOT EXISTS tickets (
  id bigserial PRIMARY KEY, code text UNIQUE NOT NULL,          -- 'TCK-000123'
  title text NOT NULL, description text NOT NULL,
  status text NOT NULL CHECK (status IN ('open','in_progress','resolved','closed')),
  priority text NOT NULL CHECK (priority IN ('low','medium','high','urgent')),
  category text NOT NULL,
  requester_sub text NOT NULL, requester_dept text NOT NULL,
  assignee_sub text, assignee_dept text NOT NULL,
  classification smallint NOT NULL DEFAULT 1 CHECK (classification BETWEEN 0 AND 3),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz, closed_by text, resolution text
);
CREATE INDEX IF NOT EXISTS tickets_requester_idx ON tickets (requester_sub);
CREATE INDEX IF NOT EXISTS tickets_assignee_dept_idx ON tickets (assignee_dept, status);

-- code mặc định từ id nếu app không đặt (create_ticket)
CREATE OR REPLACE FUNCTION acme.ticket_code_default() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN IF NEW.code IS NULL OR NEW.code = '' THEN NEW.code := 'TCK-' || lpad(NEW.id::text, 6, '0'); END IF; RETURN NEW; END $$;
DROP TRIGGER IF EXISTS tickets_code_default ON tickets;
CREATE TRIGGER tickets_code_default BEFORE INSERT ON tickets
  FOR EACH ROW EXECUTE FUNCTION acme.ticket_code_default();

CREATE TABLE IF NOT EXISTS ticket_comments (
  id bigserial PRIMARY KEY, ticket_id bigint NOT NULL REFERENCES tickets,
  author_sub text NOT NULL, body text NOT NULL, internal boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ticket_comments_ticket_idx ON ticket_comments (ticket_id);

CREATE TABLE IF NOT EXISTS ticket_events (
  id bigserial PRIMARY KEY, ticket_id bigint NOT NULL REFERENCES tickets,
  actor_sub text NOT NULL, on_behalf_of text,
  action text NOT NULL CHECK (action IN ('create','comment','status','close')),
  approval_jti uuid, intent_id uuid UNIQUE, intent_sha256 char(64),   -- UNIQUE: mỗi intent tối đa một sự kiện
  before jsonb, after jsonb, ts timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ticket_events_ticket_idx ON ticket_events (ticket_id, ts);

-- tool_audit (contracts §5): ghi cùng transaction với UPDATE/INSERT ticket_events bằng tk_app
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

-- Quyền (least privilege): tk_app không DELETE, không DDL
REVOKE ALL ON tickets, ticket_comments, ticket_events, tool_audit FROM PUBLIC, tk_app, mcp_audit_w;
GRANT SELECT, INSERT, UPDATE ON tickets TO tk_app;
GRANT SELECT, INSERT ON ticket_comments, ticket_events, tool_audit TO tk_app;
GRANT INSERT, SELECT ON tool_audit TO mcp_audit_w;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO tk_app;
GRANT USAGE ON SEQUENCE tool_audit_id_seq TO mcp_audit_w;

-- RLS (FORCE): requester_sub = app.sub OR (assignee_dept IN app.depts AND employee) OR admin
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;         ALTER TABLE tickets FORCE ROW LEVEL SECURITY;
ALTER TABLE ticket_comments ENABLE ROW LEVEL SECURITY; ALTER TABLE ticket_comments FORCE ROW LEVEL SECURITY;
ALTER TABLE ticket_events ENABLE ROW LEVEL SECURITY;   ALTER TABLE ticket_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tk_select ON tickets;
CREATE POLICY tk_select ON tickets FOR SELECT TO tk_app USING (
  requester_sub = acme.ctx_sub()
  OR (assignee_dept = ANY (acme.ctx_depts()) AND 'employee' = ANY (acme.ctx_roles()))
  OR 'admin' = ANY (acme.ctx_roles())
);
DROP POLICY IF EXISTS tk_update ON tickets;
CREATE POLICY tk_update ON tickets FOR UPDATE TO tk_app
  USING (
    requester_sub = acme.ctx_sub()
    OR (assignee_dept = ANY (acme.ctx_depts()) AND 'employee' = ANY (acme.ctx_roles()))
    OR 'admin' = ANY (acme.ctx_roles()))
  WITH CHECK (
    requester_sub = acme.ctx_sub()
    OR (assignee_dept = ANY (acme.ctx_depts()) AND 'employee' = ANY (acme.ctx_roles()))
    OR 'admin' = ANY (acme.ctx_roles()));
DROP POLICY IF EXISTS tk_insert ON tickets;
CREATE POLICY tk_insert ON tickets FOR INSERT TO tk_app WITH CHECK (
  requester_sub = acme.ctx_sub()
  OR (assignee_dept = ANY (acme.ctx_depts()) AND 'employee' = ANY (acme.ctx_roles()))
  OR 'admin' = ANY (acme.ctx_roles())
);

-- Comment: nhìn thấy khi thấy ticket cha (RLS của tickets áp trong subquery); internal chỉ cùng assignee_dept
DROP POLICY IF EXISTS tc_select ON ticket_comments;
CREATE POLICY tc_select ON ticket_comments FOR SELECT TO tk_app USING (
  EXISTS (SELECT 1 FROM tickets t WHERE t.id = ticket_comments.ticket_id
          AND (NOT ticket_comments.internal OR t.assignee_dept = ANY (acme.ctx_depts())))
);
DROP POLICY IF EXISTS tc_insert ON ticket_comments;
CREATE POLICY tc_insert ON ticket_comments FOR INSERT TO tk_app WITH CHECK (
  author_sub = acme.ctx_sub()
  AND EXISTS (SELECT 1 FROM tickets t WHERE t.id = ticket_comments.ticket_id)
);
DROP POLICY IF EXISTS te_select ON ticket_events;
CREATE POLICY te_select ON ticket_events FOR SELECT TO tk_app USING (
  EXISTS (SELECT 1 FROM tickets t WHERE t.id = ticket_events.ticket_id)
);
DROP POLICY IF EXISTS te_insert ON ticket_events;
CREATE POLICY te_insert ON ticket_events FOR INSERT TO tk_app WITH CHECK (
  EXISTS (SELECT 1 FROM tickets t WHERE t.id = ticket_events.ticket_id)
);

-- Hàm audience: suy từ điều kiện tk_select. RLS tickets không dùng clearance nên
-- min_clearance = classification của bản nháp (mặc định 1). dept_set = nơi thấy được ticket qua
-- điều kiện phòng ban: assignee_dept (role employee) và requester_dept (nơi người yêu cầu thuộc về).
-- 'admin' thấy tất cả không phụ thuộc phòng nên không đưa vào dept_set. Sửa tk_select => sửa hàm này.
CREATE OR REPLACE FUNCTION acme.ticket_audience(draft jsonb)
RETURNS TABLE (min_clearance smallint, dept_set text[])
LANGUAGE sql STABLE SECURITY INVOKER AS $$
  SELECT coalesce((draft->>'classification')::smallint, 1::smallint),
         ARRAY(SELECT DISTINCT d FROM unnest(ARRAY[draft->>'requester_dept', draft->>'assignee_dept']) AS d
               WHERE d IS NOT NULL ORDER BY d)
$$;
GRANT EXECUTE ON FUNCTION acme.ticket_audience(jsonb) TO tk_app;

RESET ROLE;
