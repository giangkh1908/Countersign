-- Kiểm chứng RLS/quyền trên DB thật. Chạy: bash infra/postgres/verify/run.sh
-- Dùng `SET ROLE` từ superuser (không cần mật khẩu). Mọi kiểm tra là assert; lỗi => ON_ERROR_STOP.
-- Chạy từng DB bằng `\c`.

\echo == knowledge: RLS tài liệu
\c knowledge
BEGIN;
-- chunk giả (vector 1024 chiều toàn 0) cho 1 doc confidential HR, ROLLBACK ở cuối: không để lại dữ liệu
INSERT INTO chunks (document_id, ord, content, n_tokens, department, classification, allowed_roles, embedding)
SELECT id, 0, 'canary', 1, department, classification, allowed_roles, array_fill(0, ARRAY[1024])::vector
FROM documents WHERE department = 'HR' AND classification = 2 LIMIT 1;

SET LOCAL ROLE kn_app;
DO $$
DECLARE n int;
BEGIN
  -- không có ngữ cảnh -> không thấy gì
  PERFORM set_config('app.depts', '', true); PERFORM set_config('app.clearance', '', true);
  PERFORM set_config('app.roles', '', true);
  SELECT count(*) INTO n FROM documents; ASSERT n = 0, 'no-context phải 0 tài liệu, có ' || n;

  -- SALES, clearance 3, role manager: KHÔNG thấy bất kỳ tài liệu HR nào (kể cả c2/c3)
  PERFORM set_config('app.depts', 'SALES', true); PERFORM set_config('app.clearance', '3', true);
  PERFORM set_config('app.roles', 'employee,dept_manager', true);
  SELECT count(*) INTO n FROM documents WHERE department = 'HR';
  ASSERT n = 0, 'SALES thấy tài liệu HR: ' || n;
  SELECT count(*) INTO n FROM documents WHERE department = 'SALES' AND classification = 3;
  ASSERT n = 3, 'SALES c3 phải thấy 3, có ' || n;
  SELECT count(*) INTO n FROM chunks WHERE department = 'HR';
  ASSERT n = 0, 'SALES thấy chunk HR: ' || n;

  -- SALES clearance 1: không thấy c2/c3 của chính phòng mình
  PERFORM set_config('app.clearance', '1', true);
  SELECT count(*) INTO n FROM documents WHERE classification >= 2;
  ASSERT n = 0, 'clearance 1 thấy c2+: ' || n;

  -- HR clearance 2 role employee: thấy c2 HR không ràng role, KHÔNG thấy c3, không thấy tài liệu SALES
  PERFORM set_config('app.depts', 'HR', true); PERFORM set_config('app.clearance', '2', true);
  PERFORM set_config('app.roles', 'employee', true);
  SELECT count(*) INTO n FROM documents WHERE department = 'SALES'; ASSERT n = 0, 'HR thấy SALES: ' || n;
  SELECT count(*) INTO n FROM documents WHERE classification = 3; ASSERT n = 0, 'HR c2 thấy c3: ' || n;
END $$;

DO $$
DECLARE n int;
BEGIN
  PERFORM set_config('app.depts', 'HR', true); PERFORM set_config('app.clearance', '2', true);
  PERFORM set_config('app.roles', 'employee', true);
  SELECT count(*) INTO n FROM documents WHERE source_path LIKE '%hr-danh-gia-hieu-suat%';
  ASSERT n = 0, 'allowed_roles không chặn employee: ' || n;
  PERFORM set_config('app.roles', 'employee,team_lead', true);
  SELECT count(*) INTO n FROM documents WHERE source_path LIKE '%hr-danh-gia-hieu-suat%';
  ASSERT n = 1, 'team_lead phải thấy tài liệu có allowed_roles: ' || n;
  -- kn_app chỉ đọc
  BEGIN
    INSERT INTO documents (id, title, source_path, sha256, department, classification)
    VALUES (gen_random_uuid(), 'x', 'x', repeat('0', 64), 'HR', 0);
    RAISE EXCEPTION 'kn_app ghi được documents';
  EXCEPTION WHEN read_only_sql_transaction OR insufficient_privilege THEN NULL;
  END;
END $$;
ROLLBACK;
\echo OK knowledge

\echo == tickets: RLS
\c tickets
BEGIN;
SET LOCAL ROLE tk_app;
DO $$
DECLARE n int; total int;
BEGIN
  PERFORM set_config('app.sub', '', true); PERFORM set_config('app.depts', '', true);
  PERFORM set_config('app.roles', '', true);
  SELECT count(*) INTO n FROM tickets; ASSERT n = 0, 'no-context thấy ticket: ' || n;

  -- an.nguyen (SALES, employee): chỉ ticket của mình + ticket assignee_dept=SALES
  PERFORM set_config('app.sub', 'an.nguyen', true); PERFORM set_config('app.depts', 'SALES', true);
  PERFORM set_config('app.roles', 'employee', true);
  SELECT count(*) INTO n FROM tickets
   WHERE NOT (requester_sub = 'an.nguyen' OR assignee_dept = 'SALES');
  ASSERT n = 0, 'SALES employee thấy ticket ngoài phạm vi: ' || n;
  SELECT count(*) INTO n FROM tickets WHERE assignee_dept = 'HR' AND requester_sub <> 'an.nguyen';
  ASSERT n = 0, 'SALES thấy ticket HR của người khác: ' || n;
  -- comment internal của HR không lộ cho SALES
  SELECT count(*) INTO n FROM ticket_comments c JOIN tickets t ON t.id = c.ticket_id
   WHERE c.internal AND t.assignee_dept <> 'SALES';
  ASSERT n = 0, 'lộ comment internal khác phòng: ' || n;

  -- tam.vu không phải employee? (vẫn employee) -> dùng sub lạ, không role: chỉ thấy ticket của mình
  PERFORM set_config('app.sub', 'khong.ton.tai', true); PERFORM set_config('app.roles', '', true);
  SELECT count(*) INTO n FROM tickets; ASSERT n = 0, 'sub lạ thấy ticket: ' || n;

  -- admin thấy tất cả
  PERFORM set_config('app.roles', 'admin', true);
  SELECT count(*) INTO n FROM tickets; ASSERT n = 100, 'admin phải thấy 100, có ' || n;
END $$;
ROLLBACK;
\echo OK tickets

\echo == analytics: an_reader chỉ thấy view, đúng phòng, đã mask
\c analytics
BEGIN;
SET LOCAL ROLE an_reader;
DO $$
DECLARE n int; p text;
BEGIN
  BEGIN
    PERFORM 1 FROM core.customers LIMIT 1;
    RAISE EXCEPTION 'an_reader đọc được core.customers';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  PERFORM set_config('app.depts', '', true); PERFORM set_config('app.roles', '', true);
  SELECT count(*) INTO n FROM api.v_orders; ASSERT n = 0, 'no-context thấy đơn: ' || n;
  PERFORM set_config('app.depts', 'HR', true);
  SELECT count(*) INTO n FROM api.v_orders; ASSERT n = 0, 'HR thấy đơn SALES/CS: ' || n;
  PERFORM set_config('app.depts', 'CS', true);
  SELECT count(*) INTO n FROM api.v_customers WHERE owning_dept <> 'CS'; ASSERT n = 0, 'CS thấy khách ngoài CS';
  SELECT count(*) INTO n FROM api.v_customers; ASSERT n = 4, 'CS phải thấy 4 khách, có ' || n;
  SELECT phone INTO p FROM api.v_customers LIMIT 1;
  ASSERT p ~ '^\*+\d{3}$', 'phone chưa mask: ' || p;
  PERFORM set_config('app.roles', 'management', true);
  SELECT count(*) INTO n FROM api.v_orders; ASSERT n = 300, 'management phải thấy 300, có ' || n;
END $$;
ROLLBACK;
\echo OK analytics
