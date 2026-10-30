-- analytics (contracts §3.4, §3.6). Chạy bằng `postgres` trên DB analytics; idempotent.
-- Schema: core (bảng gốc, an_owner), api (view security_barrier cho an_reader), acme (hàm ngữ cảnh).
CREATE SCHEMA IF NOT EXISTS core AUTHORIZATION an_owner;
CREATE SCHEMA IF NOT EXISTS api  AUTHORIZATION an_owner;
CREATE SCHEMA IF NOT EXISTS acme AUTHORIZATION an_owner;

GRANT CONNECT ON DATABASE analytics TO an_owner, an_reader, mcp_audit_w;
GRANT USAGE ON SCHEMA public TO an_reader, mcp_audit_w;
GRANT USAGE ON SCHEMA api TO an_reader;
-- an_reader KHÔNG có USAGE trên core, acme (view chạy với quyền an_owner)

SET ROLE an_owner;

-- Ngữ cảnh do CODE của MCP đặt bằng SET LOCAL (không có SQL tự do nên không thể tự đặt GUC).
CREATE OR REPLACE FUNCTION acme.ctx_depts() RETURNS text[] LANGUAGE sql STABLE AS
  $$ SELECT coalesce(string_to_array(nullif(current_setting('app.depts', true), ''), ','), '{}'::text[]) $$;
CREATE OR REPLACE FUNCTION acme.ctx_is_management() RETURNS boolean LANGUAGE sql STABLE AS
  $$ SELECT 'management' = ANY (coalesce(string_to_array(nullif(current_setting('app.roles', true), ''), ','), '{}'::text[])) $$;

CREATE TABLE IF NOT EXISTS core.customers (
  id bigint PRIMARY KEY, name text NOT NULL,
  segment text NOT NULL CHECK (segment IN ('Enterprise','SMB','Retail')),
  region text NOT NULL CHECK (region IN ('Bắc','Trung','Nam')),
  phone text, email text, tax_code text,                       -- PII (giả)
  account_manager_sub text, owning_dept text NOT NULL
);
CREATE TABLE IF NOT EXISTS core.products (
  id bigint PRIMARY KEY, sku text UNIQUE NOT NULL, name text NOT NULL, category text NOT NULL,
  price_vnd bigint NOT NULL CHECK (price_vnd >= 0)
);
CREATE TABLE IF NOT EXISTS core.orders (
  id bigint PRIMARY KEY, customer_id bigint NOT NULL REFERENCES core.customers,
  order_date date NOT NULL,
  status text NOT NULL CHECK (status IN ('completed','cancelled','refunded','pending')),
  total_vnd bigint NOT NULL CHECK (total_vnd >= 0),
  sales_rep_sub text, owning_dept text NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_date_idx ON core.orders (order_date);
CREATE INDEX IF NOT EXISTS orders_customer_idx ON core.orders (customer_id);
CREATE TABLE IF NOT EXISTS core.order_items (
  id bigint PRIMARY KEY, order_id bigint NOT NULL REFERENCES core.orders,
  product_id bigint NOT NULL REFERENCES core.products,
  quantity int NOT NULL CHECK (quantity > 0), unit_price_vnd bigint NOT NULL CHECK (unit_price_vnd >= 0)
);
CREATE INDEX IF NOT EXISTS order_items_order_idx ON core.order_items (order_id);

-- RLS FORCE trên bảng gốc (lớp phụ; policy TO an_owner): phòng trong app.depts hoặc role management
ALTER TABLE core.customers ENABLE ROW LEVEL SECURITY; ALTER TABLE core.customers FORCE ROW LEVEL SECURITY;
ALTER TABLE core.orders ENABLE ROW LEVEL SECURITY;    ALTER TABLE core.orders FORCE ROW LEVEL SECURITY;
ALTER TABLE core.order_items ENABLE ROW LEVEL SECURITY; ALTER TABLE core.order_items FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cust_dept ON core.customers;
CREATE POLICY cust_dept ON core.customers FOR ALL TO an_owner
  USING (owning_dept = ANY (acme.ctx_depts()) OR acme.ctx_is_management()) WITH CHECK (true);
DROP POLICY IF EXISTS ord_dept ON core.orders;
CREATE POLICY ord_dept ON core.orders FOR ALL TO an_owner
  USING (owning_dept = ANY (acme.ctx_depts()) OR acme.ctx_is_management()) WITH CHECK (true);
DROP POLICY IF EXISTS item_dept ON core.order_items;
CREATE POLICY item_dept ON core.order_items FOR ALL TO an_owner
  USING (EXISTS (SELECT 1 FROM core.orders o WHERE o.id = order_items.order_id)) WITH CHECK (true);

-- View security_barrier (mask PII; lọc phòng ban bên trong view)
CREATE OR REPLACE VIEW api.v_customers WITH (security_barrier = true) AS
  SELECT id, name, segment, region,
         regexp_replace(phone, '\d(?=\d{3})', '*', 'g')    AS phone,
         regexp_replace(email, '^(.).*(@.*)$', '\1***\2')  AS email,
         regexp_replace(tax_code, '\d(?=\d{3})', '*', 'g') AS tax_code,
         account_manager_sub, owning_dept
  FROM core.customers
  WHERE owning_dept = ANY (acme.ctx_depts()) OR acme.ctx_is_management();
CREATE OR REPLACE VIEW api.v_orders WITH (security_barrier = true) AS
  SELECT id, customer_id, order_date, status, total_vnd, sales_rep_sub, owning_dept
  FROM core.orders
  WHERE owning_dept = ANY (acme.ctx_depts()) OR acme.ctx_is_management();
CREATE OR REPLACE VIEW api.v_order_items WITH (security_barrier = true) AS
  SELECT i.id, i.order_id, i.product_id, i.quantity, i.unit_price_vnd
  FROM core.order_items i JOIN core.orders o ON o.id = i.order_id
  WHERE o.owning_dept = ANY (acme.ctx_depts()) OR acme.ctx_is_management();
CREATE OR REPLACE VIEW api.v_products WITH (security_barrier = true) AS
  SELECT id, sku, name, category, price_vnd FROM core.products;
CREATE OR REPLACE VIEW api.v_sales_daily WITH (security_barrier = true) AS
  SELECT order_date, owning_dept, count(*) AS n_orders, sum(total_vnd) AS revenue_vnd
  FROM core.orders
  WHERE status = 'completed' AND (owning_dept = ANY (acme.ctx_depts()) OR acme.ctx_is_management())
  GROUP BY order_date, owning_dept;

-- Quyền: an_reader chỉ SELECT trên api.v_*, không quyền nào trên core.*
REVOKE ALL ON ALL TABLES IN SCHEMA core FROM PUBLIC, an_reader;
REVOKE SELECT (phone, email, tax_code) ON core.customers FROM PUBLIC, an_reader;
REVOKE ALL ON SCHEMA core, acme FROM PUBLIC, an_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA api FROM PUBLIC, an_reader;
GRANT SELECT ON api.v_customers, api.v_orders, api.v_order_items, api.v_products, api.v_sales_daily TO an_reader;

-- tool_audit (§3.6) cho tool đọc của analytics-mcp
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
REVOKE ALL ON tool_audit, tool_audit_id_seq FROM PUBLIC, an_reader;
GRANT INSERT, SELECT ON tool_audit TO mcp_audit_w;
GRANT USAGE ON SEQUENCE tool_audit_id_seq TO mcp_audit_w;

RESET ROLE;
