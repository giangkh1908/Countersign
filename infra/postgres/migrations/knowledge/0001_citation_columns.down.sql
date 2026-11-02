-- 0001_citation_columns (down): bỏ mọi thứ thêm ở up. Dữ liệu chunk sinh lại được từ nguồn.
DROP TABLE IF EXISTS index_meta;
DROP INDEX IF EXISTS chunks_tsv_seg_gin;
DROP INDEX IF EXISTS chunks_article_idx;
ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_char_range;
ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_seg;
ALTER TABLE chunks DROP COLUMN IF EXISTS fts_text;
ALTER TABLE chunks DROP COLUMN IF EXISTS char_end;
ALTER TABLE chunks DROP COLUMN IF EXISTS char_start;
ALTER TABLE chunks DROP COLUMN IF EXISTS chapter;
ALTER TABLE chunks DROP COLUMN IF EXISTS clause;
ALTER TABLE chunks DROP COLUMN IF EXISTS article;
DROP INDEX IF EXISTS documents_doc_num_idx;
ALTER TABLE documents DROP COLUMN IF EXISTS index_sig;
ALTER TABLE documents DROP COLUMN IF EXISTS doc_num;
