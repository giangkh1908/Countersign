-- 0002_embedding_dim (down): đưa chunks.embedding về vector(1024) như đường cơ sở 30-knowledge.sql.
-- Cùng cơ chế dừng/TRUNCATE với up khi chunks còn dữ liệu ở chiều khác (MIGRATE_FORCE_REEMBED=1).
SELECT set_config('migrate.target_dim', '1024', true),
       set_config('migrate.force', :'force_reembed', true) \gset

ALTER TABLE chunks    NO FORCE ROW LEVEL SECURITY;      -- xem giải thích ở up
ALTER TABLE documents NO FORCE ROW LEVEL SECURITY;

DO $mig$
DECLARE
  tgt   int := current_setting('migrate.target_dim')::int;
  force boolean := current_setting('migrate.force') = '1';
  cur   int;
  n     bigint;
BEGIN
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

-- Khi 0001.down chạy tiếp ngay sau đó, bảng index_meta bị xoá cùng; chạy riêng thì giữ nhất quán.
UPDATE index_meta SET value = '1024' WHERE key = 'embed_dim';
