# acme-mcp-docs

MCP server tra cứu tài liệu nội bộ (RAG hybrid), cổng 8101. Tool `search_documents` (chỉ đọc):
ACL (phòng ban/clearance/roles) kiểm ở retriever và kiểm lại ở service, spotlighting nội dung,
ghi taint `(max_class, dept_set)` vào Redis (fail-closed với class >= 1 khi Redis lỗi).
Cũng có `POST /internal/taint/forget {thread_id}`.

- Chạy: `uvicorn mcp_docs.main:app`. Thiết kế: `docs/design/02-mcp-servers.md` §5.
- Ingest: `uv run python -m data.generator` rồi `uv run python -m mcp_docs.ingest [--corpus-dir data/generated] [--force]`
  (env `DOCS_INGEST_DATABASE_URL` role `kn_ingest`; idempotent theo sha256 + ACL).
- Env chính: `MCP_DATABASE_URL` (role `kn_app`), `MCP_REDIS_URL`, `DOCS_EMBEDDER` (`fake_hash` | `gateway_http`),
  `DOCS_GATEWAY_URL/KEY`, `DOCS_RETRIEVER`, `DOCS_RERANK`.

## Embedding ở M1

Mặc định `DOCS_EMBEDDER=fake_hash` (tất định, băm n-gram, 1024 chiều; ROADMAP cho phép mock ở M1).
Adapter `gateway_http` (`POST {gateway}/embeddings`, model `acme-embed`) đã viết và test bằng
MockTransport nhưng gateway M1 chưa có endpoint này. Ingest và query phải dùng cùng một embedder.

## Trạng thái kiểm chứng

Adapter `pgvector_hybrid` (retriever + indexer) và job ingest đã viết nhưng CHƯA kiểm trên Postgres thật
(SQL bám 02 §5.3 và `30-knowledge.sql`). Test nghiệp vụ chạy trên `FakeRetriever`/`FakeIndexer`.
