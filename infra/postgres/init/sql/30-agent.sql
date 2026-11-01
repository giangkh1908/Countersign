-- agent (contracts §5). Chạy bằng `postgres` trên DB agent; idempotent.
GRANT CONNECT ON DATABASE agent TO ag_owner, ag_app;
GRANT USAGE ON SCHEMA public TO ag_app;

-- Bảng do checkpointer setup() (chạy bằng ag_owner) tạo sau này cũng tự cấp DML cho ag_app.
ALTER DEFAULT PRIVILEGES FOR ROLE ag_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ag_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ag_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ag_app;

SET ROLE ag_owner;

CREATE TABLE IF NOT EXISTS conversations (
  thread_id uuid PRIMARY KEY, user_sub text NOT NULL, title text,
  created_at timestamptz NOT NULL DEFAULT now(), last_active_at timestamptz NOT NULL DEFAULT now(),
  total_cost_micro_usd bigint NOT NULL DEFAULT 0, deleted_at timestamptz
);
CREATE INDEX IF NOT EXISTS conversations_user_active_idx ON conversations (user_sub, last_active_at DESC);

RESET ROLE;
