GRANT CONNECT ON DATABASE agent TO ag_owner, ag_app;
GRANT USAGE ON SCHEMA public TO ag_app;
-- TODO(M3): ag_app chỉ DML, GRANT sau khi checkpointer setup() chạy bằng ag_owner.
