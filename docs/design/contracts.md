# Hợp đồng dùng chung

Nguồn chân lý cho tên service, cổng, danh tính, quyền, lỗi, schema DB và quy tắc code. Viết từ code và `docker-compose.yml` hiện tại. Muốn đổi thì sửa file này cùng lúc với code, và ghi ADR nếu là quyết định kiến trúc.

Mục 9 (Ports & Adapters) là quy tắc bắt buộc, `CLAUDE.md` dẫn tới đây.

## 1. Service và cổng

| Service | Package | Cổng | Mạng | Profile | Ghi chú |
|---|---|---|---|---|---|
| `postgres` | pgvector/pgvector:pg17 | 5432 | core | mặc định | Một cluster, nhiều database (mục 5) |
| `redis-state` | redis:8 | 6379 | core | mặc định | Phiên BFF, taint, intent; ACL theo user |
| `keycloak` | Keycloak 26.8.1 | 8080 | edge, core | mặc định | Realm `acme`, alias `keycloak.acme.local` |
| `gateway` | `packages/gateway` | 8000 | core, egress | mặc định | Service duy nhất ra Internet, giữ khoá provider |
| `mock-provider` | `packages/mock_provider` | 8900 | core | mặc định | Provider giả tất định cho test và E2E |
| `docs-mcp` | `packages/mcp_docs` | 8101 | core | mặc định | MCP Streamable HTTP tại `/mcp` |
| `agent` | `packages/agent` | 8200 | core | mặc định | LangGraph, API nội bộ, không ra Internet |
| `bff` | `packages/bff` (+ SPA `web/`) | 8300 | edge, core | mặc định | Phục vụ SPA cùng origin, `/auth/*`, `/api/*` |
| `tickets-mcp` | `packages/mcp_tickets` | 8102 | core | `tickets` | Giữ khoá riêng ký intent |
| `approval-signer` | `packages/approval_signer` | 8310 | core | `tickets` | Giữ khoá riêng ký approval, không DB, không Redis |
| `prometheus`, `grafana` | image gốc | 9090, 3000 | core, edge | `obs` | Scrape `/metrics` bằng bearer |
| `migrate` | job một lần | | core | mặc định | Migration (dữ liệu mẫu nạp từ host: `data/load_seed.sh`) |
| `notify-mcp` | | | | `notify` | Chưa làm (A1) |

Nguyên tắc mạng:
- `core` là mạng `internal`, không ra Internet. Chỉ `gateway` thuộc `egress`.
- MCP server, agent và signer không có đường ra ngoài; mọi lưu lượng LLM đi qua gateway.
- Dev chạy HTTP, thêm `127.0.0.1 keycloak.acme.local` vào file hosts để trình duyệt và container thấy cùng issuer.

Endpoint vận hành của mọi service HTTP: `GET /healthz` (không auth, 200 hoặc 503) và `GET /metrics` (bắt buộc `Authorization: Bearer` từ `METRICS_TOKEN_FILE`).

Container chạy `read_only`, `cap_drop: ALL`, `no-new-privileges`. Secret là file mount ở `/run/secrets`, sinh bởi `scripts/gen-secrets.sh`; app đọc qua biến `<TÊN>_FILE`.

## 2. Luồng token và audience

Keycloak realm `acme`. Client:

| Client | Loại | Việc |
|---|---|---|
| `chat-ui` | confidential, standard flow + PKCE | Đăng nhập người dùng, do BFF giữ |
| `agent-service` | confidential, không service account | Agent đổi token sang các đích |
| `llm-gateway`, `docs-mcp`, `tickets-mcp`, `approval-signer` | chỉ làm audience | Đích của token |

Các client khai báo trong `realm-acme.json` đều tắt password grant. Riêng E2E (chỉ dev) dùng `admin-cli` ở realm `master` và tự tạo client tạm `e2e-test` có password grant, rồi xoá khi kết thúc.

```
Trình duyệt --cookie--> BFF --exchange (aud=agent-service)--> agent
                         |                                     |-- exchange (aud=docs-mcp) --> docs-mcp
                         |                                     |-- exchange (aud=tickets-mcp) --> tickets-mcp
                         |                                     '-- API key + user token (aud=llm-gateway) --> gateway
                         '-- exchange (aud=approval-signer, giữ trong phiên) --> approval-signer
```

Quy tắc (chi tiết và bằng chứng: [ADR-005](../adr/ADR-005-token-flow.md)):
- Token đăng nhập (`aud=chat-ui`) và refresh token chỉ ở BFF, mã hoá AES-GCM trong phiên Redis. Trình duyệt chỉ có cookie `HttpOnly`, `SameSite=Strict` và header CSRF.
- Mỗi hop dùng Standard Token Exchange V2 (RFC 8693), mỗi request đúng một audience và đúng scope của đích. Không chuyển tiếp nguyên token.
- Keycloak không chặn gộp audience hay lọt scope, nên adapter `TokenBroker` tự kiểm hậu điều kiện: `aud` đúng một phần tử và `scope` nằm trong tập đã xin; sai thì lỗi.
- Resource server kiểm `iss`, `aud`, `exp`, chữ ký (thuật toán trong allowlist) và `azp` theo allowlist: docs-mcp và tickets-mcp nhận `agent-service`; agent nhận `chat-ui`; signer nhận `chat-ui`. Token phải có `sub`, `dept`, `clearance`.
- Agent không bao giờ có token `aud=approval-signer`: không gán scope `signer:approve` cho `agent-service`.
- Claim: `sub`, `sid`, `dept` (mảng phòng ban), `clearance` (0 đến 3), `realm_access.roles`, `scope`, `azp`.
- Cấu hình: `KEYCLOAK_ISSUER` (chuỗi so với `iss`) tách khỏi `KEYCLOAK_JWKS_URI` (nơi lấy khoá).

## 3. Scope và vai trò

| Scope | Cấp cho | Dùng ở |
|---|---|---|
| `agent:invoke` | `chat-ui` | agent |
| `signer:approve` | `chat-ui` | approval-signer |
| `llm:invoke` | `agent-service` | gateway |
| `docs:read` | `agent-service` | docs-mcp (`search_documents`) |
| `tickets:read`, `tickets:write` | `agent-service` | tickets-mcp |

Vai trò realm: `employee`, `team_lead`, `dept_manager`, `management`, `admin`, `auditor`. Vai trò, phòng ban, cấp mật đi vào GUC `app.roles`, `app.depts`, `app.clearance`, `app.sub` trong transaction của MCP; RLS của Postgres đọc các GUC này. Ma trận quyền theo tool và kênh gửi chưa làm (A1, dự thảo ở [ADR-007](../adr/ADR-007-actions-cache-observability.md)).

## 4. Định dạng lỗi

- Gateway theo OpenAI: `{"error":{"message","type","param","code"}}`. Mã: `invalid_request` 400; `invalid_api_key`, `key_revoked`, `key_expired`, `invalid_end_user_token` 401; `forbidden`, `model_not_allowed` 403; `not_found` 404; `request_too_large` 413; `internal_error` 500; `all_providers_failed` 502; `service_unavailable` 503. Message cố định, không lộ chi tiết.
- Tool MCP: kết quả lỗi có `code`, `message`, `retryable`, `details?`. Mã: `unauthorized`, `forbidden`, `not_found`, `invalid_argument`, `rate_limited`, `approval_required`, `approval_invalid`, `approval_expired`, `approval_mismatch`, `approval_replayed`, `intent_not_found`, `intent_expired`, `intent_mismatch`, `intent_unrenderable`, `conflict`, `upstream_unavailable`, `internal_error`. Signer dùng cùng mã trong body lỗi HTTP.
- MCP 401 do `AuthMiddleware` trả `error_description` thuộc `expired|audience|signature|malformed` kèm `resource_metadata` ([ADR-003](../adr/ADR-003-mcp-host-auth.md)).
- BFF: `{"error":{"code","message","retryable","request_id"}}`, mọi response có `X-Request-Id`.
- Lỗi không chứa URL, header, khoá hay nội dung người dùng.

## 5. Postgres

Một cluster, mỗi service một database và role riêng. Mọi role `NOSUPERUSER NOBYPASSRLS`. Role `*_owner` chạy migration, role `*_app` chạy runtime (có `statement_timeout`), nên runtime không sửa được schema. Bảng có RLS dùng `FORCE ROW LEVEL SECURITY`.

| Database | Role runtime | Bảng chính |
|---|---|---|
| `gateway` | `gw_app`, `gw_report` (đọc, cho Grafana) | `departments`, `api_keys`, `usage_events` (partition theo tháng), `audit_log` |
| `knowledge` | `kn_app` (đọc, chịu RLS), `kn_ingest` | `documents`, `chunks`, `tool_audit` |
| `tickets` | `tk_app` | `tickets`, `ticket_comments`, `ticket_events`, `tool_audit` |
| `agent` | `ag_app` | `conversations`, bảng checkpoint LangGraph |
| `keycloak` | `kc_app` | của Keycloak |

- `api_keys`: khoá lưu dạng HMAC-SHA256 với pepper (`secret_hmac`), không lưu khoá thô.
- `departments`, `api_keys`: không có budget hay chính sách PII.
- `usage_events`: mỗi request chat một dòng (alias, model, token, chi phí micro USD, độ trễ, mã trạng thái, `end_user_sub`).
- `audit_log`, `tool_audit`: append-only (trigger chặn UPDATE, DELETE, TRUNCATE), chuỗi hash HMAC với khoá ngoài DB (`AUDIT_HMAC_KEY_FILE`), không lưu plaintext prompt. Role `mcp_audit_w` ghi audit của MCP.
- `chunks`: `department`, `classification` (0 public, 1 internal, 2 confidential, 3 secret), `allowed_roles`, `embedding vector(EMBED_DIM)` (mặc định 1024; trần HNSW 2000 chiều với pgvector 0.8.7), `tsv` (FTS không dấu), chỉ mục HNSW và GIN. Chính sách `chunk_acl` và `doc_acl` cho `kn_app`: phòng ban khớp (hoặc `ALL`), `classification <= app.clearance`, và `allowed_roles` rỗng hoặc giao với `app.roles`. GUC thiếu thì không thấy dòng nào. Cột trích dẫn (`article`, `clause`, `chapter`, `char_start/end`, `fts_text`, `tsv_seg`, `documents.doc_num/index_sig`) và bảng `index_meta` do migration `0001_citation_columns`, số chiều embedding do `0002_embedding_dim` (`infra/postgres/migrations/knowledge/`, runner `infra/postgres/migrate.sh`, bảng `schema_migrations`, service `knowledge-migrate`); `30-knowledge.sql` giữ làm đường cơ sở. Chi tiết ở [rag-citations.md](rag-citations.md) §2.
- `tickets`: RLS theo `app.sub`, `app.depts`, `app.roles`; `ticket_events.intent_id` là `UNIQUE` để mỗi intent ghi tối đa một lần; hàm `acme.ticket_audience(draft)` cho cờ `possible_downgrade`.
- Dữ liệu mẫu: user, phòng ban và cấp mật của 16 người dùng nằm trong `infra/keycloak/realm-acme.json`.

## 6. Redis

Một instance (`redis-state`), bắt buộc mật khẩu, ACL theo user (`infra/redis/users-state.acl.tmpl`). Cache thật (Q1) sẽ thêm instance riêng.

| Khoá | Người dùng | Nội dung |
|---|---|---|
| `bff:sess:*` | `bff` | Phiên, token mã hoá, tập thẻ bị từ chối, bộ đếm thẻ |
| `mcp:taint:{sub}:{thread_id}`, `mcp:taint:{sub}:recent` | `docs`, `tickets` | Taint theo thread và gần đây |
| `mcp:tickets:intent:{id}`, `mcp:tickets:jti:{jti}` | chỉ `tickets` | Intent đang chờ và `jti` đã dùng |

`redis-state` dùng `noeviction` và AOF. Khi Redis lỗi, thao tác ghi và đọc taint đóng an toàn (từ chối hoặc cờ `taint_unknown`).

## 7. Tool MCP hiện có

| Server | Tool | Scope | Ghi chú |
|---|---|---|---|
| docs-mcp | `search_documents(query, top_k, department_filter?)` | `docs:read` | Lọc ACL trong SQL và RLS; kết quả bọc spotlighting, đánh dấu không đáng tin; ghi taint |
| tickets-mcp | `list_my_tickets`, `get_ticket`, `search_tickets` | `tickets:read` | RLS theo người gọi |
| tickets-mcp | `prepare_close_ticket(code, resolution)` | `tickets:write` | Chỉ tạo intent đã ký, không đổi dữ liệu |
| tickets-mcp | `prepare_create_ticket(title, body, category, assignee_dept, priority?, classification?)` | `tickets:write` | Như trên; `code` cấp lúc commit. Quyền theo ma trận ([actions-roles.md](actions-roles.md) §1) |
| tickets-mcp | `commit_intent(intent_id, approval_token)` | `tickets:write` | Ghi sau khi kiểm approval ([approval.md](approval.md)) |

Mỗi tool khai báo `required_scopes`, timeout và giới hạn kích thước output; `ToolInvoker` bọc xử lý: kiểm schema, scope, rate limit, timeout, cắt output, audit. Chưa có `get_document`, `prepare_create_ticket`, `notify-mcp`.

API nội bộ khác:
- Agent: `POST /threads`, `GET /threads`, `GET /threads/{id}/messages`, `DELETE /threads/{id}`, `POST /threads/{id}/runs` (SSE), `POST /threads/{id}/resume`.
- Trích dẫn (R2, [rag-citations.md](rag-citations.md) §5): sự kiện SSE `citations` có `data = {items[], sentences[], answer_status, verify}`; `items[]` theo `Citation` (§5.2), `sentences[] = {id, start, end, cites, verdict}` (`verdict` có thể `null` với câu không phải khẳng định), `answer_status ∈ {answered, partially_verified, refused}`, `verify = {enabled, pairs, judge_calls, ms, input_tokens, output_tokens, judge_errors, evidence_mismatch, invalid_refs, cost_usd?}`. Sự kiện được phát khi có `items` hoặc `answer_status != answered`. `GET /threads/{id}/messages` trả thêm, trên mỗi tin `assistant` có trích dẫn, các trường cùng tên: `citations` (= `items`), `sentences`, `answer_status`, `verify`, để nạp lại lịch sử không mất cờ "chưa kiểm chứng" và trạng thái từ chối. Khung ≤ 60.000 byte (agent cắt `passage`, đặt `passage_truncated`). BFF chỉ chuyển tiếp, không ghi nội dung citations vào log. Cấu hình agent: `AGENT_VERIFY_CITATIONS` (`on|off`, mặc định `on`), `AGENT_VERIFY_JUDGE_ADAPTER` (`gateway_llm`), `AGENT_VERIFY_JUDGE_ALIAS` (`acme-judge`), `AGENT_VERIFY_MAX_CONCURRENCY` (4), `AGENT_VERIFY_MAX_PAIRS` (12), `AGENT_VERIFY_REQUIRE_CITATION` (true), `AGENT_VERIFY_ON_UNSUPPORTED` (`flag|drop`, mặc định `flag`), `AGENT_VERIFY_MIN_SUPPORTED_RATIO` (0,5). `search_documents` trả thêm `doc_num, article, clause, chapter, char_start, char_end, text` (text thô đã sanitize; agent không chuyển cho mô hình).
- BFF: `GET /auth/login`, `/auth/callback`, `POST /auth/logout`, `POST /api/chat`, `/api/resume`, `/api/intents/verify`, `/api/approvals`, `GET /api/me`, `/api/threads`.
- Signer: `POST /v1/intents/verify`, `POST /v1/approvals`.
- Gateway: `POST /v1/chat/completions` (OpenAI-compatible, header `Authorization` là khoá API, `X-Acme-User-Token` là token người dùng `aud=llm-gateway`). `/v1/embeddings` thêm ở R1.

## 8. Cấu hình

Biến môi trường chính; mọi secret có dạng `<TÊN>_FILE`.

| Biến | Ý nghĩa |
|---|---|
| `ACME_ENV` | `dev`, `test`, `eval`. Adapter `permissive` chỉ tạo được khi `eval` |
| `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URI` | Mục 2 |
| `GW_PROVIDER_OVERRIDE` | Chọn adapter provider; mặc định `mock` |
| `EVENT_SINK_ADAPTER` | `postgres` hoặc `json_log` |
| `MCP_AUDIENCE`, `MCP_ALLOWED_AZP` | Audience và `azp` hợp lệ của MCP server |
| `AGENT_CHECKPOINT_ENCRYPTION_KEY_FILE` | Base64 của 32 byte; thiếu hoặc sai thì agent không khởi động ([ADR-004](../adr/ADR-004-checkpoint-encryption.md)) |
| `BFF_SESSION_KEY_FILE`, `BFF_OIDC_CLIENT_SECRET_FILE` | Khoá phiên và secret client `chat-ui` |
| `INTENT_TTL_S` (300), `APPROVAL_TTL_S` (120) | Hạn intent và approval |
| `BFF_MAX_CARDS_PER_THREAD_HOUR` (10), `BFF_REJECTED_TTL_S` (600) | Giới hạn thẻ duyệt |

Alias model nằm ở `packages/gateway/config/models.yaml` (hiện `acme-fast`, `acme-smart`, `acme-judge`, `acme-embed`); id model lấy từ đó, không hardcode. `acme-judge` (R2) tạm dùng cùng chain với `acme-fast`; key của agent (`bootstrap-gateway-keys.sh`) được phép alias này, không có alias runtime riêng; key cấp trước R2 phải chạy `--rotate` (script bỏ qua key còn hợp lệ). `eval.judge_alias` khác verifier vẫn để mở (rag-citations §10). Provider chat có `anthropic` và `mock`.

`acme-embed` là block `kind: embedding` (`adapter`, `model`, `dim`, thêm `base_url`, `timeout_s` tuỳ adapter). Mặc định `adapter: mock_hash` (dim 1024, khớp schema pgvector). Dùng embedding thật: đổi block sang `adapter: openai_compatible` kèm `base_url` và `model` của nhà cung cấp, đặt `GW_EMBEDDING_API_KEY` (hoặc `_FILE`); không sửa code. `POST /v1/embeddings` theo chuẩn OpenAI: `input` là chuỗi hoặc mảng tối đa 32 phần tử, `encoding_format` là `float` hoặc `base64`; dùng cùng auth và kiểm `allowed_models` như chat; không qua PII/guard; ghi `usage_events` như chat (`output_tokens` = 0).

## 9. Ports & Adapters (bắt buộc)

Mục tiêu: thêm vendor hoặc biến thể mới là thêm một file adapter, một dòng registry và một block config, không sửa service, route hay test nghiệp vụ.

### 9.1 Quy tắc

1. **Port đặt tên theo năng lực, không theo vendor.** `ChatProvider`, không phải `ClaudeClient`. Method là động từ của năng lực (`complete`, `stream`, `embed`, `search`), chỉ khai báo method mà consumer gọi.
2. **Python dùng `abc.ABC` và `@abstractmethod`.** Adapter và fake kế thừa tường minh. `typing.Protocol` chỉ để gõ kiểu cho object thư viện bên thứ ba.
3. **Kiểu dữ liệu và lỗi trung lập ở biên** (`ChatRequest`, `Usage`, `Principal`, `Intent`, `ProviderError`, `TokenInvalid`...). Adapter dịch exception của vendor sang các lỗi này; message lỗi không chứa URL, header, khoá hay nội dung người dùng.
4. **Tách file.** `ports/` (ABC, kiểu, lỗi), `adapters/<vendor>.py` (mỗi vendor một file), `factory.py`. `ports/` không import vendor.
5. **Factory dùng registry dict và lazy import**, không dùng chuỗi `if/elif`. Tên lạ thì raise `XxxNotConfigured` kèm danh sách tên hợp lệ:
   ```python
   _REGISTRY: dict[str, Callable[[Settings], ChatProvider]] = {
       "anthropic": _load_anthropic,   # lazy: from .adapters.anthropic import AnthropicProvider
       "mock": _load_mock,
   }
   def build_provider(name: str, settings: Settings) -> ChatProvider:
       try:
           loader = _REGISTRY[name]
       except KeyError:
           raise ProviderNotConfigured(f"unknown provider; known: {sorted(_REGISTRY)}") from None
       return loader(settings)
   ```
   Config riêng của vendor nằm trong block mang tên vendor. Factory nối vào DI để test override ở một chỗ.
6. **Mối quan tâm cắt ngang dùng decorator cùng port**: retry, circuit breaker, fallback, metrics (chỉ ghi metadata, không ghi payload). Factory bọc sẵn nên vendor mới hưởng luôn.
7. **Plumbing dùng chung bằng composition**: `RetryingHttpClient` (timeout, phân loại lỗi, 4xx khác 429 thì fail fast, backoff có jitter, giới hạn số lần). Adapter giữ một instance, không kế thừa. Độ sâu kế thừa tối đa: port, base trừu tượng dùng chung (khi có từ hai adapter chung luồng), adapter.
8. **Business logic chỉ import port và factory.** Leak-grep chạy trong CI (`scripts/leak-grep.sh`); cả ba lệnh phải không có kết quả:
   ```
   grep -rniE "anthropic|gemini|google|keycloak|presidio|underthesea|pgvector|qdrant|fastmcp|langfuse" packages/*/src --include=*.py | grep -vE "/adapters/|factory\.py|settings\.py"
   grep -rniE "onnxruntime|torch|tokenizers|transformers|sentence_transformers|huggingface_hub" packages/gateway/src --include=*.py
   grep -rnE "\bfetch\(|XMLHttpRequest|EventSource|fetch-event-source|axios|keycloak-js|oidc-client" web/src --include=*.ts --include=*.tsx | grep -vE "src/api/client\.ts|\.test\.tsx?$"
   ```
9. **Test.** `Fake<Port>` kế thừa port (ở `packages/common/.../testing/` hoặc `testing.py` của từng package). Test nghiệp vụ dùng fake; test HTTP chỉ cho chính adapter. Mỗi factory có một test (tên đúng thì chạy, tên lạ thì báo lỗi).
10. **Không trừu tượng hoá quá mức.** Port phải có (a) adapter thứ hai thật hoặc đã lên kế hoạch, hoặc (b) fake thay I/O, hoặc (c) chặn tên vendor lan vào business logic. Không đạt thì là module thường. Không bọc: Postgres, client Redis, FastAPI, LangGraph và `BaseCheckpointSaver`, giao thức OpenAI-compatible, OIDC, OpenTelemetry. Không DI container, không plugin auto-discovery.
11. **Adapter `permissive`** (bỏ qua kiểm approval/intent, để làm ablation) chỉ tạo được khi `ACME_ENV=eval`; factory raise lúc khởi động nếu env khác.

### 9.2 Port hiện có

| Package | Port | Adapter |
|---|---|---|
| common | `TokenVerifier` | `oidc_jwks` |
| common | `TokenBroker` | `oauth_token_exchange` (decorator caching theo `(sub, sid, audience, scopes)`) |
| common | `EventSink` (usage và audit, hash-chain) | `postgres`, `json_log` |
| common | `Clock`, `RateLimiter`, `ToolServerHost` | `system`; `in_memory`; `mcp_sdk` |
| gateway | `ChatProvider`, `EmbeddingProvider`, `KeyStore` | `anthropic`, `mock`; `mock_hash`, `openai_compatible`; `postgres` |
| docs-mcp | `Embedder`, `Reranker`, `DocumentLoader`, `DocumentRetriever`, `DocumentIndexer` | `fake_hash`, `gateway_http`; `none`; `markdown`; `pgvector_hybrid`; `pgvector_indexer` |
| agent | `ToolProvider`, `ConversationRepository`, `ServiceProbe` | `mcp_http`; `postgres`, `memory`; `http_probe` |
| tickets-mcp | `TicketRepository` | `postgres` |
| acme_common (dùng chung cho mọi MCP ghi) | `IntentIssuer`, `ApprovalVerifier`, `ReplayGuard`, `IntentExecutor` | `es256_jws`; `es256_jwt`; `redis`, `in_memory`; executor do từng MCP cài |
| approval-signer | `IntentVerifier`, `ApprovalSigner` | `es256_jws`; `es256_jwt` |

Hạ tầng intent dùng chung nằm ở `acme_common`: ports/types (`intent_*.py`), adapter Redis/ES256 tham số hoá theo `issuer` và `redis_prefix`, và `services/intent_commit.py` (`IntentCommitService`: thứ tự kiểm approval, máy trạng thái, idempotency). MCP ghi chỉ cài `IntentExecutor` (phân quyền lại + thực thi). Ma trận quyền: `acme_common/services/capabilities.py`. Signer tin nhiều `iss` (`INTENT_ISSUER_NAMES`); khoá công khai ở `INTENT_PUBLIC_KEYS_DIR/<iss>/<kid>.pem`, op gắn với issuer (`rendering.ISSUER_OPS`).

Muốn chuyển ticket sang Jira thì thêm `adapters/jira.py`, một dòng registry và block config; quy tắc quyền, intent/approval và audit trong service giữ nguyên.

### 9.3 Cấu trúc package Python

```
packages/<svc>/src/<svc>/
├─ ports/          # ABC, kiểu trung lập, lỗi (không import vendor)
├─ adapters/       # <vendor>.py: nơi duy nhất import SDK của vendor
├─ factory.py      # registry dict và lazy loader
├─ services/       # business logic, chỉ phụ thuộc port
├─ api/            # FastAPI route (hoặc api.py khi chỉ có một file)
└─ settings.py     # pydantic-settings, block theo vendor
```

Thư mục chỉ có một file thì là module (`api.py`, `tools.py`, `services.py`...); không giữ thư mục một file. `decorators.py` (retry, fallback, metrics cùng port) chỉ tạo khi có decorator thật; hiện chưa package nào có. Không tạo thư mục hay file rỗng cho thứ chưa làm. Layout thực tế khác nhau theo package: `agent` có `adapters/ agents/ graph/ ports/` cùng `api.py`, `run_service.py`; `approval_signer` có `adapters/ ports/` cùng `api.py`, `approval.py`, `rendering.py`; `mcp_tickets` có `adapters/ ports/ services/` cùng `tools.py`; `mcp_docs` có `adapters/ api/ ingest/ ports/ services/`; `bff` có `adapters/ api/ services/`.

`packages/common` (`acme_common`) giữ phần dùng chung và chỉ dùng thuật ngữ trung lập (OIDC, JWKS); tên vendor chỉ xuất hiện ở adapter và settings.

### 9.4 Frontend (`web/`, React và TypeScript)

- Một `src/api/client.ts` duy nhất chứa `request()` (JSON, CSRF, xử lý hết phiên) và `sse()`. Component không gọi `fetch`.
- Interface trong `src/api/types.ts`; test dùng fake hoặc MSW.
- Markdown render qua `react-markdown` và `rehype-sanitize`. Không lưu token ở JS hay localStorage.
- BFF đặt CSP chặt (`default-src 'self'`, `script-src 'self'`, `frame-ancestors 'none'`); cookie `__Host-sid` (dev `sid`), CSRF double-submit `X-CSRF-Token`.
