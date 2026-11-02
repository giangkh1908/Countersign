-- 0002_embedding_dim (up): đưa chunks.embedding về vector(EMBED_DIM) (rag-citations §2.2).
-- migrate.sh truyền psql -v embed_dim=... và -v force_reembed=0|1 (không dùng envsubst: image postgres không có).
-- Đổi chiều khi chunks còn dữ liệu: dừng, trừ khi MIGRATE_FORCE_REEMBED=1 (khi đó TRUNCATE chunks + xoá index_sig).
SELECT set_config('migrate.target_dim', :'embed_dim', true),
       set_config('migrate.force', :'force_reembed', true) \gset

-- kn_owner bị FORCE RLS chặn (chỉ có policy cho kn_app/kn_ingest): count/UPDATE sẽ thấy 0 dòng.
-- Tắt FORCE trong transaction này (DDL có tính transaction), bật lại ở cuối.
ALTER TABLE chunks    NO FORCE ROW LEVEL SECURITY;
ALTER TABLE documents NO FORCE ROW LEVEL SECURITY;

DO $mig$
DECLARE
  tgt   int := current_setting('migrate.target_dim')::int;
  force boolean := current_setting('migrate.force') = '1';
  cur   int;
  n     bigint;
BEGIN
  IF tgt > 2000 THEN
    RAISE EXCEPTION 'EMBED_DIM=% vượt trần HNSW 2000 của kiểu vector; dùng halfvec hoặc giảm chiều', tgt;
  END IF;
  SELECT atttypmod INTO cur FROM pg_attribute
   WHERE attrelid = 'public.chunks'::regclass AND attname = 'embedding' AND NOT attisdropped;
  IF cur IS DISTINCT FROM tgt THEN
    SELECT count(*) INTO n FROM chunks;
    IF n > 0 AND NOT force THEN
      RAISE EXCEPTION 'chunks còn % dòng ở vector(%), đích là vector(%): đặt MIGRATE_FORCE_REEMBED=1 để xoá chunks và nạp lại', n, cur, tgt;
    END IF;
    IF n > 0 THEN
      TRUNCATE chunks;
      UPDATE documents SET index_sig = '';
    END IF;
    DROP INDEX IF EXISTS chunks_embedding_hnsw;
    EXECUTE format('ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(%s) USING NULL', tgt);
  END IF;
  CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
END
$mig$;

ALTER TABLE chunks    FORCE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

INSERT INTO index_meta (key, value) VALUES ('embed_dim', :'embed_dim')
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
