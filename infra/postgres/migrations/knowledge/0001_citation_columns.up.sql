-- 0001_citation_columns (up): cột trích dẫn, full-text tách từ, bảng index_meta (rag-citations §2.1, §2.2).
-- Chạy bằng kn_owner trong một transaction do migrate.sh mở; mọi lệnh idempotent.

-- documents
ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_num   text;            -- "45/2019/QH14"; NULL với tài liệu ACME
ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_sig text NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS documents_doc_num_idx ON documents (doc_num);

-- chunks: vị trí trích dẫn
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS article    text;             -- "38", "38a"
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS clause     text;             -- "2" | "1-3" | NULL
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chapter    text;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS char_start int;              -- offset trong article_text
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS char_end   int;
ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_char_range;          -- ADD CONSTRAINT không có IF NOT EXISTS
ALTER TABLE chunks ADD CONSTRAINT chunks_char_range CHECK
  ((char_start IS NULL AND char_end IS NULL) OR (char_start >= 0 AND char_end > char_start));
CREATE INDEX IF NOT EXISTS chunks_article_idx ON chunks (document_id, article);

-- full-text tuỳ chọn tách từ; `tsv` hiện có (không tách từ) giữ nguyên
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fts_text text;               -- văn bản đã qua TextSegmenter; NULL khi chưa tính
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv_seg tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', acme.immutable_unaccent(coalesce(fts_text, '')))) STORED;
CREATE INDEX IF NOT EXISTS chunks_tsv_seg_gin ON chunks USING gin (tsv_seg);

-- model/chiều/phiên bản đang dùng (embed_model, embed_dim, chunker_version, fts_mode); ingest ghi
CREATE TABLE IF NOT EXISTS index_meta (key text PRIMARY KEY, value text NOT NULL DEFAULT '');
-- Quyền: default privileges của kn_owner trong 30-knowledge.sql đã cấp SELECT cho kn_app và DML cho kn_ingest.
