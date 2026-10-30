-- gateway (contracts §3.1). Chạy bằng `postgres` trên DB gateway; idempotent.
GRANT CONNECT ON DATABASE gateway TO gw_owner, gw_app, gw_report;
GRANT USAGE ON SCHEMA public TO gw_app, gw_report;
CREATE SCHEMA IF NOT EXISTS acme AUTHORIZATION gw_owner;

SET ROLE gw_owner;

CREATE TABLE IF NOT EXISTS departments (
  code        text PRIMARY KEY,                 -- 'SALES','ENG','HR','CS','IT','EVAL'
  name        text NOT NULL,
  monthly_budget_micro_usd bigint NOT NULL,
  pii_policy  text NOT NULL DEFAULT 'mask' CHECK (pii_policy IN ('mask','block','allow'))
);

CREATE TABLE IF NOT EXISTS api_keys (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  prefix        char(12) UNIQUE NOT NULL,       -- phần public, hiển thị được
  secret_hmac   bytea NOT NULL,                 -- HMAC-SHA256(key=GW_KEY_PEPPER, msg=secret_utf8)
  name          text NOT NULL,
  owner_type    text NOT NULL CHECK (owner_type IN ('service','department','user')),
  owner_ref     text NOT NULL,                  -- client_id / dept code / keycloak sub
  department    text NOT NULL REFERENCES departments(code),
  allowed_models text[] NOT NULL,               -- acme-fast, acme-smart, acme-auto, acme-embed, acme-judge (chỉ EVAL)
  rpm_limit     int NOT NULL, tpm_limit int NOT NULL, max_concurrency int NOT NULL DEFAULT 8,
  monthly_budget_micro_usd bigint,              -- NULL = dùng budget phòng ban
  trust_end_user_token boolean NOT NULL DEFAULT false,
  expose_debug  boolean NOT NULL DEFAULT false,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked','expired')),
  created_by    text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz, revoked_at timestamptz, revoked_by text, revoked_reason text,
  last_used_at  timestamptz
);
CREATE INDEX IF NOT EXISTS api_keys_department_idx ON api_keys (department);

CREATE TABLE IF NOT EXISTS usage_events (        -- PARTITION BY RANGE (ts), mỗi tháng một partition
  id bigserial, ts timestamptz NOT NULL DEFAULT now(),
  request_id uuid NOT NULL, key_id uuid NOT NULL, department text NOT NULL, end_user_sub text,
  alias text NOT NULL, provider text, model text,
  input_tokens int, output_tokens int, cached_input_tokens int,
  cost_micro_usd bigint NOT NULL DEFAULT 0,
  latency_ms int, ttft_ms int, gateway_overhead_ms int, sidecar_ms int,
  cache text NOT NULL DEFAULT 'miss' CHECK (cache IN ('miss','exact','semantic')),
  fallback_count smallint NOT NULL DEFAULT 0, route_reason text,
  pii_entities int NOT NULL DEFAULT 0, guard_score real,
  status_code smallint NOT NULL, error_code text,
  PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);
CREATE INDEX IF NOT EXISTS usage_events_dept_ts_idx ON usage_events (department, ts);
CREATE INDEX IF NOT EXISTS usage_events_key_ts_idx ON usage_events (key_id, ts);
CREATE INDEX IF NOT EXISTS usage_events_request_idx ON usage_events (request_id);

-- Partition theo tháng: hàm tạo (idempotent) + partition DEFAULT để không bao giờ lỗi khi quên tạo.
CREATE OR REPLACE FUNCTION acme.ensure_usage_partition(month_start date) RETURNS void LANGUAGE plpgsql AS $$
DECLARE m date := date_trunc('month', month_start)::date; nm text := 'usage_events_' || to_char(m, 'YYYY_MM');
BEGIN
  EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF usage_events FOR VALUES FROM (%L) TO (%L)',
                 nm, m, (m + interval '1 month')::date);
END $$;
CREATE TABLE IF NOT EXISTS usage_events_default PARTITION OF usage_events DEFAULT;
-- Tạo sẵn 2026-01 .. 2027-12 (job/migration định kỳ gọi acme.ensure_usage_partition cho tháng kế)
SELECT acme.ensure_usage_partition(make_date(y, m, 1)) FROM generate_series(2026, 2027) y, generate_series(1, 12) m;

CREATE SEQUENCE IF NOT EXISTS audit_log_id_seq;
CREATE TABLE IF NOT EXISTS audit_log (
  id bigint PRIMARY KEY DEFAULT nextval('audit_log_id_seq'),   -- app lấy nextval TRƯỚC khi băm
  ts timestamptz NOT NULL,               -- app gán trước khi băm; KHÔNG dùng DEFAULT now()
  request_id uuid, actor_type text NOT NULL, actor_id text NOT NULL, end_user_sub text,
  action text NOT NULL,
  resource text, decision text NOT NULL CHECK (decision IN ('allow','deny','error')),
  details jsonb NOT NULL DEFAULT '{}',   -- KHÔNG chứa prompt plaintext; chỉ prompt_sha256
  hmac_kid smallint NOT NULL,
  prev_hash bytea NOT NULL, hash bytea NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON audit_log (ts);
CREATE INDEX IF NOT EXISTS audit_log_request_idx ON audit_log (request_id);

-- Chặn UPDATE/DELETE/TRUNCATE kể cả với owner (chỉ chống thao tác SQL thường; xem giới hạn ở contracts §3.1)
CREATE OR REPLACE FUNCTION acme.audit_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION '% on % is not allowed (append-only)', TG_OP, TG_TABLE_NAME USING ERRCODE = '42501'; END $$;
DROP TRIGGER IF EXISTS audit_log_no_mod ON audit_log;
CREATE TRIGGER audit_log_no_mod BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION acme.audit_immutable();
DROP TRIGGER IF EXISTS audit_log_no_trunc ON audit_log;
CREATE TRIGGER audit_log_no_trunc BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION acme.audit_immutable();

-- Quyền theo bảng (least privilege)
REVOKE ALL ON departments, api_keys, usage_events, audit_log FROM PUBLIC, gw_app, gw_report;
GRANT SELECT ON departments TO gw_app, gw_report;
GRANT SELECT, INSERT, UPDATE ON api_keys TO gw_app;          -- UPDATE: last_used_at, revoke
GRANT SELECT, INSERT ON usage_events, audit_log TO gw_app;
GRANT SELECT ON usage_events TO gw_report;                   -- Grafana
GRANT USAGE ON SEQUENCE audit_log_id_seq TO gw_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO gw_app;     -- usage_events_id_seq

RESET ROLE;
