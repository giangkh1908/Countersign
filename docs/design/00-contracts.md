# 00 — Hợp đồng dùng chung (Shared Contracts)

> **Nguồn chân lý duy nhất** cho tên dịch vụ, cổng, mạng, Redis keyspace, schema Postgres, JWT claims, mã lỗi, biến môi trường.
> Mọi tài liệu thiết kế `01..04` và mọi dòng code phải khớp file này. Muốn đổi thì sửa file này trước và ghi ADR.
> Phiên bản 1.3, 2026-10-29. Khi mâu thuẫn với `DECISIONS-v1.2.md` thì `DECISIONS-v1.2.md` thắng.

### Changelog v1.3
Tham chiếu: `D15` trong `design/DECISIONS-v1.2.md`, `docs/adr/ADR-002-ui-react-bff.md` (thay ADR-001); `N01`, `N02` trong `docs/reviews/review-02-opus.md`.
- **D15 UI = React + TypeScript + BFF ngay từ MVP:** bỏ Chainlit (đã thay). Service `ui` đổi thành `bff` (`packages/bff`, 8300, `edge`+`core`), phục vụ SPA `web/` + `/auth/*` + `/api/*`; phiên ở `redis-state` key `bff:sess:{sid}`, Redis ACL user `bff` (§1, §2).
- **Sửa N01/N02 (luồng token, thay phần Keycloak của D13):** token đăng nhập `aud=chat-ui` và không gửi cho agent; BFF exchange sang `aud=agent-service` (gửi agent mỗi request) và `aud=approval-signer` (chỉ trong session server); `agent-service` exchange sang `llm-gateway` + 3 MCP, không tới signer; bỏ client `bff` riêng; signer kiểm `azp == chat-ui`; test D13/F22 phải dùng chính token agent cầm (§4, §4.1, §8).
- Mã lỗi mới `intent_unrenderable` (422, signer) và lỗi BFF (§6.3, §6.4); env BFF (§7); quy tắc frontend và leak-grep cho `web/src` (§9.1, §9.3).

- **D16 đồng bộ sau D15:** role quản trị thống nhất `admin`; client scope `agent:invoke`, `signer:approve` (§4); tập `display_fields[].kind` chuẩn theo `05` mục 5.3; render model thêm `server_time`; khoá phụ phiên BFF `:pend/:lock/:gate/:rl` (§2.1); user Redis `bff` không `MULTI/WATCH/EVAL`; `TokenBroker`/`TokenVerifier` ở `acme_common` (§9.2); mã lỗi và env BFF bổ sung (§6.4, §7); endpoint BFF/agent bổ sung (§6.2); CSP thêm `object-src 'none'` (§9.3); realm `chat-ui` (§4). Đã đưa đủ 11 mục "Phụ thuộc contracts v1.3" của `07` §9 vào đây.

### Changelog v1.2.1
Tham chiếu: `D13` (phần Keycloak bị D15 thay), `D14` trong `design/DECISIONS-v1.2.md`.
- **D13 Tách token cho approval-signer:** bỏ audience mapper `approval-signer` trên token đăng nhập của `chat-ui`; UI backend tự token-exchange (RFC 8693) lấy token `aud=approval-signer`, giữ trong session phía server; quyền exchange tới `approval-signer` chỉ cấp cho `chat-ui`/`bff`; `agent-service` chỉ exchange tới 3 MCP; signer kiểm `aud` + `azp ∈ {chat-ui, bff}` + `sub == intent.sub` (§4, §4.1, §8).
- **D14 Gộp phụ thuộc v1.2:** port `AnchorStore`; `EventSink.flush()` + `append(record, sync=)`; `IntentIssuer.issue(op, target, draft, ctx)`; sidecar dùng `PiiDetector` adapter `underthesea_ner`; Redis TTL intent = `exp`+30s (330s); xoay khoá ES256 overlap 15 phút; EVAL trần 160 USD + key `eval-regression`; env `MODELS_LOCK_SHA256`, `SIDECAR_TOKEN_PREV`, `*_TLS_*`; cột `tickets.classification`, `tool_audit.intent_id`, `ticket_events.intent_id`; `acme-embed` -> `sidecar/embed`; admin cache API (§2, §3, §5, §6.2, §7, §9.2).
- Đề xuất trong 01§21, 02§12, 03§15, 04§23, 05§14: chấp nhận trừ mục ghi ở cuối file này ("Đề xuất bị bác/hoãn v1.2.1").

### Changelog v1.2
Tham chiếu: `Dn` = mục n trong `design/DECISIONS-v1.2.md`; `Rnn` = phát hiện trong `docs/reviews/review-01-opus.md`.
- **D0 Định khung:** dự án sản phẩm phát triển tự do, hướng tới chạy thật trong doanh nghiệp. Lộ trình theo milestone M0–M7, mục tiêu số là SLO/acceptance.
- **D1 Phê duyệt ràng buộc giao dịch (R01, R05):** thêm service `approval-signer` (8310) giữ khoá ký approval; tool ghi = cặp `prepare_<op>` + `commit_intent`; thêm **intent JWS** do tickets-mcp ký; approval token ràng buộc `intent_id` + `intent_sha256` (thay cho ràng buộc tham số `args` do UI/agent dựng); `ticket_events` đổi cột `args_sha256` thành `intent_id`, `intent_sha256`; mã lỗi `intent_not_found`, `intent_expired`, `intent_mismatch` (§4, §6.3, §8).
- **D2 Tách gateway (R06, R14):** thêm `policy-sidecar` (8010, embed/guard/NER); gateway không nạp onnxruntime/torch/tokenizers; một runtime embedding duy nhất (§1, §7, §9.2).
- **D3 Supply chain model (R07):** `models.lock`, `huggingface_hub` pin revision, chỉ `*.safetensors`/`*.onnx`, sidecar verify hash lúc khởi động (§7.1).
- **D4 Cache (R08, R09):** exact cache `scope_hash` có `sub`; semantic cache chỉ populate từ nguồn tin cậy; `x-acme-cache`/`x_acme.cache` chỉ cho key admin/EVAL (§2.2, §6.2).
- **D5 Degraded mode Redis (R20):** hạn mức in-memory chia theo số worker/instance, chỉ alias rẻ, TTL L1 ≤ 30s, metric `gw_degraded_overspend_max_usd`, hết 600s -> 503 (§2.3).
- **D6 Audit (R15):** hash chain dùng HMAC-SHA256 với khoá ngoài DB (`AUDIT_HMAC_KEY`), anchor mỗi giờ ra kho append-only ngoài DB; audit tool ghi của tickets-mcp ghi đồng bộ cùng transaction (§3.1, §3.6).
- **D7 PII nội bộ (R12):** checkpoint LangGraph mã hoá mặc định, retention 30 ngày (§3.5, §7).
- **D8 Taint (R16):** `mcp:taint:{sub}` do docs-mcp ghi; `risk_flags:["possible_downgrade"]` trong intent (§2.1, §4).
- **D9 Analytics (R19):** MVP chỉ tool tham số hoá; `run_readonly_sql` + HMAC ctx chuyển sang mục "Tuỳ chọn sau v1.0" (§3.4).
- **D10 Đánh giá:** benchmark + security regression + user study; adapter `permissive` vẫn chỉ ở `ACME_ENV=eval`.
- **D11 Ports cân bằng (R18):** bảng port viết lại: thêm `Clock`, `IntentIssuer`, `IntentVerifier`, `ApprovalSigner` (nay ở approval-signer), `ApprovalVerifier`; gộp `UsageSink`+`AuditSink` -> `EventSink`; bỏ port `ChatModelFactory`, `Chunker`, `SqlValidator` (§9.2).
- **D12 Khác:** giữ 2 Redis instance; Redis ACL cho `docs` (taint), `tickets` (intent, taint đọc), `signer` không dùng Redis; Keycloak client `approval-signer` (bearer-only); Presidio chỉ còn là baseline ngoài tuỳ chọn.

### Changelog v1.1
Tham chiếu: `01§20.n` = mục n trong "Đề xuất sửa contracts" của `01-gateway.md`; `02§12.Pn`; `03§15.n`; `04§22.n`. `QĐ` = quyết định của orchestrator.
- Chi phí khi stream: chunk usage cuối có `x_acme{request_id,cost_usd,cache,fallbacks,provider,model}`; thêm `GET /v1/requests/{request_id}`; `x-acme-cost-usd` chỉ ở non-stream (§6; 01§20.5, 03§15.1).
- Header mới `X-Acme-Client-Request-Id` và W3C `traceparent` truyền xuyên suốt (§6.2; 03§15.2).
- Issuer Keycloak cố định `http://keycloak.acme.local:8080/realms/acme`, network alias, `KC_HOSTNAME`; TLS là giới hạn dev (§1, §4, §7; 02§12.P9, 04§22.2).
- Mã lỗi gateway bổ sung `invalid_request`, `request_too_large`, `forbidden`, `idempotency_conflict`, `service_unavailable`, `internal_error`; `context_too_large` giữ riêng cho token; chuẩn hoá mã lỗi tool MCP (§6; 01§20.1, 03§15.7).
- `gw:key:{prefix}` thêm `max_concurrency`, `trust_end_user_token`, `owner_type`; `pii_policy` lấy từ `departments`; công thức HMAC; `gw:idem` TTL 1h, chỉ khi client gửi header (§2.1, §3.1; 01§20.2-3, 04§22.11).
- Exact cache key thêm `top_p, stop, response_format, tool_choice, seed, tools` (§2.2; 01§20.6).
- `/metrics` mọi service yêu cầu bearer `METRICS_TOKEN`; Prometheus ở `core`+`edge` (§1, §7; 01§20.7, 04§22.1).
- `audit_log`: app gán `id`, `ts` trước khi băm; MCP có bảng `tool_audit` hash-chain dùng lib `packages/common/audit` (§3.1, §3.6; 01§20.8, 02§12.P4).
- Port `RateLimiter` thêm `acquire_slot/release_slot`; thêm port MCP `ToolRateLimiter`, `ToolAuditSink`, `ToolInvoker`; package `common` (§9.2; 01§20.11, 02§12.P13).
- Redis ACL: mỗi service một user bao trùm prefix của mình; thêm `health`, `ops +ping`; bỏ user dùng chung cho MCP; secret theo `<BIẾN>_FILE` (§2, §7; 02§12.P5, 04§22.3-4).
- Postgres: thêm `gw_report`, `ag_owner`, `kc_app`, `lf_app`, `mcp_audit_w`; `conversations` thêm cột; `kn_ingest` có policy; `documents` bật RLS (§3; 02§12.P10, 03§15.4-5, 04§22.5).
- `acme.immutable_unaccent(text)` IMMUTABLE cho cột GENERATED; cast clearance an toàn trong mọi policy (§3.2; 02§12.P1-2).
- analytics: bỏ `security_invoker`; view `security_barrier` do `an_owner` sở hữu, lọc qua `acme.ctx_depts()` (SECURITY DEFINER); `an_reader` không có quyền bảng gốc; role viết thường (§3.4; 02§12.P3, P11, P14).
- Phòng ban `EVAL` (budget cứng 120 USD ở v1.1, nay 160 USD, xem v1.2.1) và alias `acme-judge` (Gemini 3.1 Pro trước, Claude Sonnet dự phòng: khác họ với agent để giảm self-preference bias), chỉ key EVAL (§3.1, §5; 04§22.6-7).
- `GW_PROVIDER_OVERRIDE=mock` thay mọi phần tử chain bằng adapter `mock`, giữ tên model gốc để tính giá (§7; 04§22.14).
- Ablation E4: adapter `ApprovalVerifier=permissive`, chỉ khi `ACME_ENV=eval`, profile compose `eval` (§9.2, §7; 04§22.8).
- Tool ghi cần approval token; `approval_jti` trong kết quả; `expected_updated_at` -> `conflict` (§4, §6.3; 03§15.7-8). *(v1.2 thay bằng luồng intent, xem D1.)*
- Token exchange cache key `(sub, aud, sorted scopes)`, in-process, TTL `exp-30s` (§4, §9.2; 03§15.6).
- Env theo service dạng bảng, gồm `DOCS_GATEWAY_URL/KEY`, `MCP_HOST`, `MCP_PORT`, `METRICS_TOKEN`, Redis URL theo service, `<BIẾN>_FILE` (§7; 02§12.P8, P12, 03§15.9, 01§20.7).
- Langfuse: profile `obs` tuỳ chọn, bản v3 (ClickHouse/MinIO, nặng); thêm job `migrate`, `seed`, endpoint vận hành `/healthz`, `/metrics`, overlay bench `gateway-b` (§1; 04§22.9-10).
- `pending_action` ở 03 §2 thêm `agent`, `audience` (QĐ21). Endpoint nội bộ agent <-> ui giữ ở 03, không đưa vào contracts (03§15.10).
- `common` chỉ nói "OIDC/JWKS" trung lập (§9.2; 04§22.15). `config/gateway.yaml` thêm vào danh sách config (§3.1; 01§20.4). Thứ tự stage cố định, `router` trước `cache` (§7; 01§20.10).
- Không áp / để sau: xem bảng trạng thái ở mục cuối mỗi file 01-04.

---

## 1. Dịch vụ, cổng, mạng

| Service (compose) | Image / package | Cổng nội bộ | Expose ra host | Mạng | Ghi chú |
|---|---|---|---|---|---|
| `keycloak` | quay.io/keycloak/keycloak (pin digest) | 8080 | 8080 | edge, core | Realm `acme`. Network alias `keycloak.acme.local` (trên `core` và `edge`); `KC_HOSTNAME=http://keycloak.acme.local:8080` |
| `postgres` | pgvector/pgvector:pg17 (pin digest) | 5432 | — | core | Một cluster, nhiều database |
| `redis-state` | redis:8 (pin digest) | 6379 | — | core | `noeviction`, AOF `everysec` |
| `redis-cache` | redis:8 (pin digest, có Query Engine/vector) | 6379 | — | core | `allkeys-lru`, không persistence |
| `gateway` | `packages/gateway` | 8000 | 8000 (dev) | core, **egress** | **Service duy nhất được ra Internet** và giữ khoá provider. **Không** nạp onnxruntime/torch/tokenizers/model HF; PII regex thuần Python; gọi `policy-sidecar` qua HTTP nội bộ |
| `policy-sidecar` | `packages/policy_sidecar` | 8010 | — | **core only** | Không giữ khoá nào, **không egress**. `/v1/embed` (bge-m3 ONNX), `/v1/guard` (Prompt Guard 2), `/v1/pii/ner` (underthesea CRF). Verify `models.lock` lúc khởi động (§7.1). Bearer nội bộ `SIDECAR_TOKEN` |
| `approval-signer` | `packages/approval_signer` | 8310 | — | **core only** | Service nhỏ (≤ ~300 dòng; FastAPI + PyJWT/cryptography, không dependency nặng), không egress, không Redis. Giữ **khoá riêng ES256 ký approval token**; xác minh intent JWS của tickets-mcp; trả render model. BFF **không** giữ khoá |
| `mock-provider` | `packages/mock_provider` | 8900 | — | core | Giả lập OpenAI/Anthropic/Gemini |
| `docs-mcp` | `packages/mcp_docs` | 8101 | — | core | Streamable HTTP `/mcp` |
| `tickets-mcp` | `packages/mcp_tickets` | 8102 | — | core | Giữ khoá riêng ký **intent**; xác minh approval token bằng khoá công khai của signer |
| `analytics-mcp` | `packages/mcp_analytics` | 8103 | — | core | MVP: chỉ tool tham số hoá (D9) |
| `agent` | `packages/agent` | 8200 | — | core | LangGraph + API nội bộ |
| `bff` | `packages/bff` (FastAPI; image multi-stage: build SPA `web/` bằng node, runtime python) | 8300 | 8300 | edge, core | Phục vụ SPA đã build (cùng origin, không CORS) + `/auth/*` + `/api/*` (D15). Giữ phiên OIDC, token-exchange, gọi `agent` và `approval-signer`. Token không xuống trình duyệt (chỉ cookie `HttpOnly`). **Không giữ khoá ký**. Dev: Vite 5173 proxy → 8300 |
| `prometheus` | prom/prometheus | 9090 | 9090 (dev) | core, **edge** (dev) | Cần `edge` để publish 9090 (Docker không publish cổng của container chỉ thuộc network `internal`). Scrape `/metrics` bằng bearer `METRICS_TOKEN` |
| `grafana` | grafana/grafana | 3000 | 3000 | edge, core | |
| `langfuse` (profile `obs`, tuỳ chọn) | langfuse/langfuse (v3) | 3001 | 3001 | edge, core | v3 cần thêm ClickHouse, MinIO, Redis riêng -> **nặng, tuỳ chọn**. Chỉ nhận metadata hoặc nội dung đã mask (D7) |
| `migrate`, `seed` | job một lần (Alembic, dữ liệu mẫu) | — | — | core | Chạy trước các service (04) |
| `gateway-b` | cùng image `gateway` | 8000 | — | core | Chỉ trong overlay `bench` (nhiều instance) |

**Endpoint vận hành** (mọi service HTTP): `GET /healthz` (không auth, chỉ trả 200/503), `GET /metrics` (**bắt buộc** `Authorization: Bearer ${METRICS_TOKEN}`). `mock-provider` thêm `/__control` (chaos).
**Compose profile:** mặc định (core), `obs` (langfuse), `bench`, `eval` (chỉ profile này đặt `ACME_ENV=eval` và cho phép adapter `permissive`).

**Mạng Docker**
- `edge`: thứ người dùng truy cập (bff, keycloak, grafana, prometheus dev, langfuse).
- `core`: `internal: true`, không ra Internet. Gồm cả `policy-sidecar` và `approval-signer`.
- `egress`: chỉ `gateway` tham gia, đây là đường duy nhất ra `api.anthropic.com` và `generativelanguage.googleapis.com`.

> **Giới hạn dev:** Keycloak và mạng nội bộ chạy HTTP, không TLS. Dev thêm dòng `127.0.0.1 keycloak.acme.local` vào file hosts của máy để trình duyệt và container thấy cùng issuer. Production (M7) phải dùng TLS nội bộ (mTLS hoặc TLS + cert nội bộ) và hostname thật.

> **Lý do:** MCP server, agent, policy-sidecar và approval-signer **không có đường ra Internet**. Prompt injection có điều khiển được agent thì cũng không có kênh exfiltrate trực tiếp. Mọi lưu lượng ra ngoài đều đi qua gateway, nên đều được lọc PII và ghi audit. Việc tách model nặng sang sidecar giữ cho tiến trình duy nhất có khoá provider và egress luôn nhỏ, ít dependency.

## 2. Redis — keyspace đầy đủ

Có **hai instance** (quyết định giữ nguyên, D12) vì hai loại dữ liệu cần chính sách bộ nhớ trái ngược:

| Instance | Chứa | `maxmemory-policy` | Persistence | Nếu mất dữ liệu |
|---|---|---|---|---|
| `redis-state` | Rate limit, budget counter, circuit breaker, thu hồi key, chống replay `jti`, intent, taint, concurrency | `noeviction` (bị đầy thì báo lỗi thay vì lặng lẽ xoá counter) | AOF `everysec` | Rate limit reset ngắn hạn; budget được reconcile lại từ Postgres; intent đang chờ mất -> user duyệt lại (an toàn); taint mất -> mất cảnh báo, xem 02 |
| `redis-cache` | Exact cache, semantic cache (vector index) | `allkeys-lru` | Không | Chỉ mất cache hit |

**Redis ACL** (`users.acl`; user `default` bị tắt; **mỗi service MỘT user bao trùm các prefix của mình**; mật khẩu nạp theo quy ước `<BIẾN>_FILE`). `approval-signer` và `policy-sidecar` **không có user Redis** (không dùng Redis):
```
user gateway   on >${REDIS_GATEWAY_PASSWORD}   ~gw:*  &gw:events  +@read +@write +@scripting +@pubsub -@dangerous
user tickets   on >${REDIS_TICKETS_PASSWORD}   ~mcp:tickets:* ~mcp:rl:tickets-mcp:* %R~mcp:taint:*  +@read +@write +@scripting -@dangerous
user docs      on >${REDIS_DOCS_PASSWORD}      ~mcp:rl:docs-mcp:* ~mcp:taint:*  +@read +@write +@scripting -@dangerous
user analytics on >${REDIS_ANALYTICS_PASSWORD} ~mcp:rl:analytics-mcp:*  +@read +@write +@scripting -@dangerous
user bff       on >${REDIS_BFF_PASSWORD}       ~bff:sess:*  +@read +@write -@dangerous   # chỉ trên redis-state (D15)
user health    on >${REDIS_HEALTH_PASSWORD}    resetkeys +ping
user ops       on >${REDIS_OPS_PASSWORD}       ~*  +@read +info +ping -@dangerous
```
`+@scripting` là bắt buộc vì token bucket, breaker, concurrency và `taint_max` chạy bằng Lua (`EVALSHA`). `docs` cần quyền đọc+ghi `mcp:taint:*` vì Lua gộp `max` (đọc giá trị cũ, ghi giá trị mới); `tickets` chỉ **đọc** taint (`%R~`). `redis-cache` dùng user `gateway` với `~gwc:*` và quyền search (`+@search` hoặc liệt kê `FT.*`; kiểm thử ACL thật sớm). User `health` có ở cả hai instance. **User `bff` (D16) chỉ dùng lệnh đơn**: không có `MULTI/WATCH/EXEC/EVAL/EVALSHA` (ACL `+@read +@write -@dangerous` không cấp `@scripting`/`@transaction`); BFF chỉ dùng `GET/SET NX EX/HSET/HGETALL/EXPIRE/INCR/DEL`, không Lua.

### 2.1 `redis-state`

| Key | Kiểu | TTL | Ghi bởi | Thao tác | Mục đích |
|---|---|---|---|---|---|
| `gw:key:{prefix}` | HASH `{key_id, hmac, dept, owner_type, allowed_models(CSV), rpm, tpm, max_concurrency, budget_micro('' = dùng budget phòng ban), trust_end_user_token, expose_debug, pii_policy, status, expires_at}`; `pii_policy` lấy từ bảng `departments` (JOIN), không phải cột của `api_keys` | 300s | gateway | `HGETALL`; nếu miss thì đọc Postgres rồi `HSET`+`EXPIRE` | Cache metadata của API key (L2). L1 là LRU trong process, TTL 10s (degraded: ≤ 30s, xem §2.3) |
| `gw:events` | PUB/SUB channel | — | gateway admin API | `PUBLISH {"type":"key_revoked","prefix":...}` | Mọi instance xoá L1 + L2 ngay -> **thu hồi < 1s** |
| `gw:rl:{scope}:{id}:req` | HASH `{tokens, ts_ms}` | `2 × window` | gateway | Lua `token_bucket.lua` (atomic) | Token bucket cho số request/phút. `scope ∈ {key, dept, user}` |
| `gw:rl:{scope}:{id}:tok` | HASH `{tokens, ts_ms}` | `2 × window` | gateway | Lua: **reserve** theo ước lượng trước khi gọi, **settle** (hoàn/trừ thêm) khi có usage thật | Token bucket cho số token/phút |
| `gw:inflight:{key_id}` | STRING int | 120s (an toàn) | gateway | `acquire_slot` (Lua) trước, `release_slot` trong `finally`; trần = `max_concurrency` | Giới hạn số request đồng thời mỗi key (chống unbounded consumption, LLM10) |
| `gw:spend:key:{key_id}:{yyyymm}` | STRING int (micro-USD) | 40 ngày | gateway | `INCRBY` sau mỗi request | Kiểm tra budget nhanh (hot counter) |
| `gw:spend:dept:{dept}:{yyyymm}` | STRING int (micro-USD) | 40 ngày | gateway | `INCRBY` | Budget phòng ban |
| `gw:cb:{provider}:state` | HASH `{state: closed\|open\|half_open, opened_at_ms, probe_lock}` | không | gateway | Lua `breaker.lua` | Trạng thái circuit breaker **chia sẻ** giữa các instance |
| `gw:cb:{provider}:win:{bucket10s}` | HASH `{ok, fail, timeout}` | 120s | gateway | `HINCRBY` | Cửa sổ trượt 60s (6 bucket) để tính tỉ lệ lỗi |
| `gw:idem:{key_id}:{idempotency_key}` | STRING (request_id) | **1h** (cấu hình được) | gateway | `SET NX` | Chống gửi trùng. **Chỉ tạo khi client gửi header** `Idempotency-Key` |
| `mcp:tickets:intent:{intent_id}` | HASH `{sha256, sub, status: pending\|committed\|cancelled}` | **330s** (= `exp` của intent 300s + 30s; D14) | tickets-mcp | `prepare_*`: `HSET` + `EXPIRE 330`; `commit_intent`: kiểm `sha256`, `sub`, `status=pending`, rồi đặt `committed` (Lua, atomic) | Ràng buộc intent đã phát hành với đúng người, đúng nội dung; dùng một lần. `sha256` = `intent_sha256` (§4) |
| `mcp:tickets:jti:{jti}` | STRING "1" | 180s (> exp của approval token) | tickets-mcp | `SET NX EX 180`. Thất bại tức là **replay**, từ chối | Approval token chỉ dùng được một lần |
| `mcp:taint:{sub}` | STRING int (max `classification` đã trả cho user) | **1800s** (30 phút), gia hạn mỗi lần ghi | docs-mcp (Lua `taint_max`) | docs-mcp ghi sau mỗi lần trả tài liệu có `classification` cao hơn; tickets-mcp **chỉ đọc** | Taint phía server (agent không giả được) để phát hiện `possible_downgrade` ở `prepare_*` (D8) |
| `bff:sess:{sid}` | HASH `{v, sub, user (JSON hiển thị, không dùng để cấp quyền), created_at, csrf, access_enc, access_exp, refresh_token_enc, id_token_enc, agent_enc, agent_exp, signer_token (enc), signer_exp}` (+ `gw_admin_enc` ở M6); các trường `*_enc` mã hoá AES-GCM (`BFF_SESSION_KEY`, AAD = sid + tên trường) | idle 30 phút (trượt, `BFF_SESSION_IDLE_S=1800`), tuyệt đối 8 giờ (`BFF_SESSION_ABS_S=28800`) | bff | `HSET`/`EXPIRE`, xoá khi logout | Phiên BFF (D15). Token chỉ ở đây, không xuống trình duyệt; agent chỉ nhận token `aud=agent-service` mỗi request. TTL token signer ≤ `BFF_SIGNER_TOKEN_TTL_S` (≤ 300s) |
| `bff:sess:{sid}:pend` | HASH `interrupt_id → JSON {thread_id, intent_id, intent_jws, op, expires_at, state, tries}`, tối đa 5 mục | cùng phiên | bff | `HSET`/`HGET`/`HDEL` | Interrupt BFF nhận từ agent; **BFF giữ `intent_jws` ở đây** (trình duyệt chỉ gửi `thread_id`/`interrupt_id`). Ngoại lệ có chủ đích duy nhất của quy tắc "không lưu intent JWS" bên dưới; xoá khi resume (D16) |
| `bff:sess:{sid}:lock` | STRING `SET NX PX 10000` | 10s | bff | `SET NX PX` | Single-flight refresh/exchange |
| `bff:sess:{sid}:gate:{interrupt_id}` | STRING `SET NX EX 150` | 150s | bff | `SET NX EX` | Chống bấm đúp Duyệt / hai tab |
| `bff:sess:{sid}:rl:{bucket}` | STRING `INCR` + `EXPIRE NX` | cửa sổ 60s (`streams`: 330s) | bff | `INCR`/`DECR`/`EXPIRE` | Rate limit và số luồng SSE theo phiên |
| `bff:sess:login:{state}` | STRING JSON `{verifier, nonce, return_to, created_at}` | 600s | bff | `SET EX`, đọc rồi `DEL` | Trạng thái đăng nhập OIDC (dùng một lần) |
| `bff:sess:u:{sha256(sub)[:16]}:appr` | STRING `INCR` | 3600s | bff | `INCR`/`EXPIRE` | Trần 30 approval/giờ theo người dùng (lớp phụ) |
| `mcp:rl:{server}:{sub}` | HASH token bucket | 120s | các MCP server (`server` ∈ `docs-mcp`, `tickets-mcp`, `analytics-mcp`) | Lua | Rate limit gọi tool theo user (chống agent chạy vòng lặp) |

**Reconcile budget:** job mỗi 5 phút tính `SUM(cost_micro_usd)` từ `gateway.usage_events` trong tháng và ghi đè `gw:spend:*`. Postgres là nguồn chân lý, Redis là counter nóng.

**Không bao giờ lưu trong Redis:** bảng ánh xạ PII (chỉ nằm trong RAM của request), plaintext API key, access token của user, nội dung prompt chưa mask, **intent JWS đầy đủ** ở các key `mcp:*` (chỉ lưu hash, sub, status); ngoại lệ duy nhất là `bff:sess:{sid}:pend` của phiên BFF (D16).

### 2.2 `redis-cache`

| Key / Index | Kiểu | TTL | Mục đích |
|---|---|---|---|
| `gwc:x:{sha256(scope_hash ‖ alias ‖ canonical_json(messages, tools, temperature, max_tokens, top_p, stop, response_format, tool_choice, seed))}` | STRING (JSON response đã nén) | 1h | **Exact cache**, chỉ khi `temperature ≤ 0.3`. `alias` là alias **đã resolve** (không phải `acme-auto`) |
| Index `gwc:sidx` (FT.CREATE, HNSW, COSINE, DIM 1024) trên prefix `gwc:s:` | — | — | Semantic cache (M4, tuỳ chọn bật) |
| `gwc:s:{uuid}` | HASH `{scope_hash TAG, alias TAG, prompt_sha TAG, source TAG, vec VECTOR, response, created_ms, hits}` | 24h | Một entry semantic cache. `source ∈ {faq_approved, admin_warmup}` |

**Công thức `scope_hash` (D4):**
- **Mặc định (per-user):** `scope_hash = sha256(sub ‖ dept ‖ clearance ‖ sorted(roles) ‖ alias ‖ system_prompt_sha ‖ tool_schema_sha)`.
- **Per-scope** (bỏ `sub`) chỉ áp dụng khi admin bật cờ `cache_scope: public_faq` cho đúng alias + system prompt đó trong `config/gateway.yaml`.
- Mọi truy vấn KNN **bắt buộc** có pre-filter `@scope_hash:{...} @alias:{...}`. Không có cache hit chéo user/phòng ban/quyền (tránh lặp lại CVE-2026-89032).

**Semantic cache (D4):** chỉ **populate từ nguồn tin cậy** (FAQ đã duyệt, admin warm-up qua admin API); **không** populate từ response của người dùng thường; luôn per-scope. Bật phải qua pilot đo `false hit rate` (M4).

**Quy tắc ẩn metadata cache (D4):** header `x-acme-cache` và trường `x_acme.cache` **chỉ trả cho key có `expose_debug = true`** (key admin hoặc phòng EVAL). User thường không thấy được trạng thái hit/miss (chống side-channel dò cache). `usage_events.cache` vẫn ghi nội bộ.

**Không cache:** response có `tool_calls`; request có `role=tool` trong messages; request mà bộ lọc PII phát hiện có PII; `stream=true` ở lần đầu (chỉ cache sau khi đã ghép xong stream).

**Đo lường (D4):** hit-rate và tiết kiệm đo trên **trace agent thật** (replay), không chỉ RAG cố định. Ưu tiên tiết kiệm qua router + **provider prompt caching**.

### 2.3 Degraded mode khi `redis-state` lỗi (D5)

Gateway chuyển sang adapter `in_memory` (RateLimiter, CircuitBreaker) khi `redis-state` không truy cập được, với ràng buộc:
- Hạn mức in-memory = `limit / (N_worker × N_instance)`, `N_worker = GW_WORKERS`, `N_instance = GW_INSTANCES` đọc từ config.
- Chỉ phục vụ alias rẻ `acme-fast`; alias khác -> 503 `service_unavailable`.
- TTL L1 của metadata key rút xuống **≤ 30s** (không còn pub/sub thu hồi tức thì, nên key bị thu hồi phải hết hiệu lực trong ≤ 30s qua kiểm tra lại DB).
- Metric `gw_degraded_overspend_max_usd` (ước tính chi vượt tối đa trong degraded); header `x-acme-degraded: 1`.
- Quá `GW_DEGRADED_MAX_S` (mặc định **600s**) -> 503 `service_unavailable`.

## 3. Postgres

Một cluster, **mỗi service một database và một role riêng**. Không role nào của ứng dụng có `SUPERUSER` hay `BYPASSRLS`. Migration bằng Alembic, mỗi package giữ migration của mình. `policy-sidecar` và `approval-signer` **không có database**.

| Database | Role (owner / runtime) | Dùng bởi |
|---|---|---|
| `gateway` | `gw_owner` / `gw_app` | gateway |
| `knowledge` | `kn_owner` / `kn_app` (chỉ SELECT) / `kn_ingest` (INSERT/UPDATE/DELETE qua policy) | docs-mcp, job ingest |
| `tickets` | `tk_owner` / `tk_app` | tickets-mcp (kể cả `tool_audit` cho tool ghi, cùng transaction) |
| `analytics` | `an_owner` / `an_reader` | analytics-mcp |
| `agent` | `ag_owner` (chạy `setup()` checkpointer, migration) / `ag_app` (runtime DML, không `CREATEROLE/CREATEDB`) | agent |
| `gateway` (đọc) | `gw_report` (chỉ SELECT `usage_events`, `departments`) | Grafana |
| `keycloak` | `kc_app` | Keycloak |
| `langfuse` | `lf_app` | Langfuse (profile `obs`) |
| `mcp_audit` (§3.6) | `mcp_audit_w` (INSERT/SELECT) | thư viện audit của MCP (tool đọc) |

### 3.1 `gateway`
```sql
CREATE TABLE departments (
  code        text PRIMARY KEY,                 -- 'SALES','ENG','HR','CS','IT'
  name        text NOT NULL,
  monthly_budget_micro_usd bigint NOT NULL,
  pii_policy  text NOT NULL DEFAULT 'mask'      -- mask|block|allow
);
-- Dữ liệu: SALES, ENG, HR, CS, IT và EVAL (phòng kỹ thuật cho đánh giá: key riêng từng thí nghiệm,
--   monthly_budget_micro_usd = 160_000_000 (trần cứng 160 USD, dự kiến chi ~130; D14), pii_policy='mask'; chỉ key EVAL được dùng alias acme-judge;
--   có key riêng `eval-regression` cho nightly regression)

CREATE TABLE api_keys (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  prefix        char(12) UNIQUE NOT NULL,       -- phần public, hiển thị được
  secret_hmac   bytea NOT NULL,                 -- HMAC-SHA256(key=GW_KEY_PEPPER, msg=secret_utf8)
  name          text NOT NULL,
  owner_type    text NOT NULL CHECK (owner_type IN ('service','department','user')),
  owner_ref     text NOT NULL,                  -- client_id / dept code / keycloak sub
  department    text NOT NULL REFERENCES departments(code),
  allowed_models text[] NOT NULL,               -- alias: acme-fast, acme-smart, acme-auto, acme-embed, acme-judge (chỉ EVAL)
  rpm_limit     int NOT NULL, tpm_limit int NOT NULL, max_concurrency int NOT NULL DEFAULT 8,
  monthly_budget_micro_usd bigint,              -- NULL = dùng budget phòng ban
  trust_end_user_token boolean NOT NULL DEFAULT false,  -- chỉ key của agent-service = true
  expose_debug  boolean NOT NULL DEFAULT false,         -- true: được thấy x-acme-cache / x_acme.cache (key admin/EVAL)
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked','expired')),
  created_by    text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz, revoked_at timestamptz, revoked_by text, revoked_reason text,
  last_used_at  timestamptz
);

CREATE TABLE usage_events (            -- PARTITION BY RANGE (ts), mỗi tháng một partition
  id bigserial, ts timestamptz NOT NULL DEFAULT now(),
  request_id uuid NOT NULL, key_id uuid NOT NULL, department text NOT NULL, end_user_sub text,
  alias text NOT NULL, provider text, model text,
  input_tokens int, output_tokens int, cached_input_tokens int,
  cost_micro_usd bigint NOT NULL DEFAULT 0,
  latency_ms int, ttft_ms int, gateway_overhead_ms int, sidecar_ms int,   -- sidecar_ms: tổng thời gian chờ policy-sidecar (phân rã độ trễ)
  cache text NOT NULL DEFAULT 'miss' CHECK (cache IN ('miss','exact','semantic')),
  fallback_count smallint NOT NULL DEFAULT 0, route_reason text,
  pii_entities int NOT NULL DEFAULT 0, guard_score real,
  status_code smallint NOT NULL, error_code text,
  PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE TABLE audit_log (
  id bigint PRIMARY KEY,                 -- app gán TRƯỚC khi băm (nextval lấy trước từ audit_log_id_seq, hoặc UUIDv7); gw_app cần USAGE trên sequence
  ts timestamptz NOT NULL,               -- app gán trước khi băm; KHÔNG dùng DEFAULT now()
  request_id uuid, actor_type text NOT NULL, actor_id text NOT NULL, end_user_sub text,
  action text NOT NULL,                  -- llm.call, key.create, key.revoke, pii.block, guard.block, ...
  resource text, decision text NOT NULL, -- allow|deny|error
  details jsonb NOT NULL DEFAULT '{}',   -- KHÔNG chứa prompt plaintext; chỉ chứa prompt_sha256
  hmac_kid smallint NOT NULL,            -- id khoá HMAC (xoay khoá)
  prev_hash bytea NOT NULL, hash bytea NOT NULL   -- hash = HMAC-SHA256(AUDIT_HMAC_KEY[hmac_kid], prev_hash ‖ canonical(row))
);
-- gw_app: chỉ INSERT, SELECT trên audit_log; trigger chặn UPDATE/DELETE kể cả với owner.
-- Hash chain TOÀN CỤC, ghi tuần tự bằng pg_advisory_xact_lock; `details` cấm float (canonical JSON tái lập được).
-- Hạn chế đã biết: advisory lock tuần tự hoá ghi audit (giữ nguyên ở v1.x; hướng mở rộng: chain theo shard/partition + anchor tổng, D12/R27).
```
**Audit chống giả mạo (D6):** khoá HMAC `AUDIT_HMAC_KEY` là secret **nằm ngoài DB** (Docker secret / secret manager), nên người chỉ có quyền DB (kể cả DBA) không tái tạo được chuỗi hợp lệ nếu sửa dữ liệu. **Anchor mỗi giờ:** job ghi bản ghi `{chain, last_id, last_hash, ts, hmac_kid, sig}` (`sig` = HMAC của các trường còn lại) ra kho **append-only ngoài DB**: dev = thư mục mount riêng chỉ-append (`AUDIT_ANCHOR_DIR`) + commit vào git repo `audit-anchors`; prod = bucket object-lock. Script verify kiểm tra chuỗi từ anchor gần nhất. **Giới hạn ghi rõ:** không chống kẻ vừa có quyền DBA vừa có `AUDIT_HMAC_KEY`; chỉ phát hiện sửa/xoá khi đối chiếu với anchor.

Cấu hình model và giá **không nằm trong DB** mà ở `config/models.yaml`, `config/pricing.yaml` và `config/gateway.yaml` (giới hạn dept/user, breaker, guard, ngưỡng cache, router, fail-policy sidecar; quản lý bằng git, review được, có `effective_from`).

### 3.2 `knowledge`
```sql
CREATE EXTENSION vector;
CREATE SCHEMA acme; CREATE EXTENSION unaccent SCHEMA acme;
-- unaccent() chỉ STABLE nên không hợp lệ trong cột GENERATED ... STORED -> hàm bọc IMMUTABLE (dùng cả lúc truy vấn)
CREATE FUNCTION acme.immutable_unaccent(text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  AS $$ SELECT acme.unaccent('acme.unaccent'::regdictionary, $1) $$;
CREATE TABLE documents (
  id uuid PRIMARY KEY, title text NOT NULL, source_path text NOT NULL, sha256 char(64) NOT NULL,
  department text NOT NULL,              -- 'ALL' = toàn công ty
  classification smallint NOT NULL,      -- 0 public, 1 internal, 2 confidential, 3 secret
  allowed_roles text[] NOT NULL DEFAULT '{}',   -- rỗng = mọi role đạt classification
  owner_sub text, version int NOT NULL DEFAULT 1,
  ingested_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE chunks (
  id bigserial PRIMARY KEY, document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  ord int NOT NULL, heading text, content text NOT NULL, n_tokens int NOT NULL,
  department text NOT NULL, classification smallint NOT NULL, allowed_roles text[] NOT NULL, -- denormalized để filter
  embedding vector(1024) NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', acme.immutable_unaccent(content))) STORED
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON chunks USING gin (tsv);
CREATE INDEX ON chunks (department, classification);
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY; ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
-- Cast clearance an toàn, áp cho MỌI policy (GUC rỗng/thiếu -> -1 -> không thấy gì):
--   coalesce(nullif(current_setting('app.clearance', true),''),'-1')::int
CREATE POLICY chunk_acl ON chunks FOR SELECT TO kn_app USING (
  (department = 'ALL' OR department = ANY (string_to_array(current_setting('app.depts', true), ',')))
  AND classification <= coalesce(nullif(current_setting('app.clearance', true),''),'-1')::int
  AND (cardinality(allowed_roles) = 0 OR allowed_roles && string_to_array(current_setting('app.roles', true), ','))
);
ALTER TABLE documents ENABLE ROW LEVEL SECURITY; ALTER TABLE documents FORCE ROW LEVEL SECURITY;
CREATE POLICY doc_acl ON documents FOR SELECT TO kn_app USING (   -- cùng điều kiện như chunk_acl
  (department = 'ALL' OR department = ANY (string_to_array(current_setting('app.depts', true), ',')))
  AND classification <= coalesce(nullif(current_setting('app.clearance', true),''),'-1')::int
  AND (cardinality(allowed_roles) = 0 OR allowed_roles && string_to_array(current_setting('app.roles', true), ','))
);
-- Ingest (kn_ingest bị FORCE RLS chặn nếu thiếu policy):
CREATE POLICY chunk_ingest ON chunks    FOR ALL TO kn_ingest USING (true) WITH CHECK (true);   -- INSERT/UPDATE/DELETE (+SELECT để upsert)
CREATE POLICY doc_ingest   ON documents FOR ALL TO kn_ingest USING (true) WITH CHECK (true);
```
docs-mcp lọc ACL **hai lớp**: điều kiện `WHERE` tường minh trong query, cộng RLS dựa trên `SET LOCAL app.*` lấy từ JWT. User không có quyền gửi SQL vào database này. **Một runtime embedding duy nhất (D2):** job ingest và query của docs-mcp đều lấy vector qua alias `acme-embed` của gateway (-> `policy-sidecar /v1/embed`), không chạy runtime embedding riêng. Sau mỗi lần trả tài liệu, docs-mcp cập nhật `mcp:taint:{sub}` = max `classification` đã trả (§2.1).

### 3.3 `tickets`
```sql
CREATE TABLE tickets (
  id bigserial PRIMARY KEY, code text UNIQUE NOT NULL,          -- 'TCK-000123'
  title text NOT NULL, description text NOT NULL,
  status text NOT NULL CHECK (status IN ('open','in_progress','resolved','closed')),
  priority text NOT NULL CHECK (priority IN ('low','medium','high','urgent')),
  category text NOT NULL,
  requester_sub text NOT NULL, requester_dept text NOT NULL,
  assignee_sub text, assignee_dept text NOT NULL,
  classification smallint NOT NULL DEFAULT 1,                   -- mức nhìn thấy của ticket đích (so với taint, D8); 1 = INTERNAL (D14)
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz, closed_by text, resolution text
);
CREATE TABLE ticket_comments (id bigserial PRIMARY KEY, ticket_id bigint REFERENCES tickets,
  author_sub text NOT NULL, body text NOT NULL, internal boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE ticket_events (id bigserial PRIMARY KEY, ticket_id bigint REFERENCES tickets,
  actor_sub text NOT NULL, on_behalf_of text, action text NOT NULL,      -- create|comment|status|close
  approval_jti uuid, intent_id uuid, intent_sha256 char(64),             -- ràng buộc với intent đã duyệt (D1)
  before jsonb, after jsonb, ts timestamptz NOT NULL DEFAULT now());
CREATE TABLE tool_audit (...);   -- hash-chain HMAC, cùng format audit_log (§3.6); ghi cùng transaction với UPDATE
-- RLS: requester_sub = app.sub
--   OR (assignee_dept = ANY(app.depts) AND 'employee' = ANY(app.roles))
--   OR 'admin' = ANY(app.roles)
-- Comment có internal = true chỉ hiện với cùng assignee_dept.
```
`commit_intent` thực hiện trong **một transaction**: `UPDATE tickets ... WHERE code=:code AND updated_at=:expected_updated_at` (0 dòng -> `conflict`), `INSERT ticket_events`, `INSERT tool_audit` (hash-chain HMAC). Lỗi ở bất kỳ bước nào -> rollback cả ba; không có thao tác ghi nào thiếu audit.

### 3.4 `analytics` (giả lập CRM/bán hàng)
- Bảng gốc (schema `core`, do `an_owner` sở hữu): `customers(id, name, segment, region, phone, email, tax_code, account_manager_sub, owning_dept)`, `products`, `orders(id, customer_id, order_date, status, total_vnd, sales_rep_sub, owning_dept)`, `order_items`.
- **MVP (D9): chỉ tool tham số hoá** (`sales_summary`, `top_customers`, `customer_lookup`, ...). Không có đường nào cho SQL do LLM sinh. Truy cập qua view `security_barrier = true` (schema `api`: `v_orders`, `v_sales_daily`, `v_customers`, `v_order_items`, `v_products`) do `an_owner` sở hữu, đã **mask** cột PII (`regexp_replace(phone, '\d(?=\d{3})', '*', 'g')`). Lọc phòng ban nằm bên trong view qua `acme.ctx_depts()` / `acme.ctx_is_management()` đọc `app.depts`/`app.roles` do **chính code của MCP** đặt bằng `SET LOCAL` (không có SQL tự do nên không thể tự đặt GUC).
- **Thu hồi mọi quyền cột PII trên bảng gốc** (`REVOKE ... (phone, email, tax_code)`); `an_reader` **không có quyền nào trên `core.*`**, chỉ `SELECT` trên `api.v_*`; `default_transaction_read_only = on`; `statement_timeout = 3s`; `idle_in_transaction_session_timeout = 5s`; `work_mem` thấp.
- RLS **`FORCE`** trên bảng gốc (policy `TO an_owner`; role `management` viết thường thấy tất cả) giữ làm lớp phụ.
- **Tuỳ chọn sau v1.0 — `run_readonly_sql` + HMAC ctx.** Thiết kế giữ nguyên để làm sau: `ANALYTICS_ENABLE_RAW_SQL=true` bật tool `run_readonly_sql`; `acme.ctx_depts()` (SECURITY DEFINER) kiểm chữ ký `app.sig` = HMAC của `sub,depts,clearance,roles,exp` (khoá `ANALYTICS_CTX_HMAC_KEY` ≥ 32 byte trong `acme.ctx_key`, `an_reader` không đọc được; chữ ký sai/hết hạn -> mảng rỗng -> 0 dòng); validator sqlglot **allowlist hàm** chặn `set_config(...)`; ép `LIMIT 200`. Mối đe doạ được chặn: SQL do LLM sinh gọi `set_config('app.depts','HR',true)` để leo quyền. Khi bật mục này mới có module `sql_validator` (module thường, không phải port) và các test E6 mở rộng. Chi tiết ở `02-mcp-servers.md`.

### 3.5 `agent`
Bảng checkpoint của `langgraph-checkpoint-postgres` (tự tạo khi `setup()`), cộng bảng `conversations(thread_id uuid PK, user_sub, title, created_at, last_active_at, total_cost_micro_usd bigint DEFAULT 0, deleted_at timestamptz)` với index `(user_sub, last_active_at DESC)`. `ag_owner` chạy `setup()` của checkpointer; `ag_app` chỉ DML.
**Bảo vệ PII nội bộ (D7):** checkpoint được **mã hoá mặc định** bằng serializer mã hoá (`AGENT_CHECKPOINT_ENCRYPTION_KEY`; API chính xác xác minh ở spike M0); **retention** thread 30 ngày (`AGENT_THREAD_RETENTION_DAYS`, job xoá định kỳ) và API xoá thread theo yêu cầu user. Langfuse (nếu bật) chỉ nhận metadata hoặc nội dung đã mask; log không chứa nội dung hội thoại.

### 3.6 Audit của MCP
Mỗi DB MCP (hoặc DB `mcp_audit` dùng chung khi runtime role chỉ đọc) có bảng `tool_audit` cùng format hash-chain HMAC với `gateway.audit_log` (`id`, `ts` do app gán trước khi băm, `hmac_kid`, `prev_hash`, `hash` = HMAC bằng `AUDIT_HMAC_KEY`; chỉ INSERT, trigger chặn UPDATE/DELETE). Mã dùng chung ở `packages/common/audit` (cùng job anchor hằng giờ như §3.1).
Cột `intent_id uuid NULL` (D14) có trong `tool_audit` (null với tool đọc); role `mcp_audit_w` giữ quyền **INSERT/SELECT** (không UPDATE/DELETE).
- **Tool ghi (tickets-mcp):** audit ghi **đồng bộ, trong cùng transaction** với `UPDATE`/`INSERT ticket_events` ở DB `tickets` (§3.3). Không ghi bất đồng bộ.
- **Tool đọc:** có thể ghi vào `mcp_audit` hoặc JSON log; biến `MCP_AUDIT_DATABASE_URL` (tuỳ chọn); luôn có JSON log.

## 4. Danh tính & token (Keycloak realm `acme`)

**User attributes:** `department` (một hoặc nhiều mã), `clearance` (0–3), `employee_id`.
**Realm roles:** `employee`, `team_lead`, `dept_manager`, `management`, `admin`, `auditor`.

| Client | Loại | Dùng cho |
|---|---|---|
| `chat-ui` | confidential, Authorization Code + PKCE; **client của BFF** (D15; không có client `bff` riêng) | Người dùng đăng nhập qua BFF. Token đăng nhập `aud=chat-ui` (audience mapper trên chính client; **không** có `agent-service` hay `approval-signer`), không gửi cho agent. Được phép token-exchange tới `agent-service` (xin scope `agent:invoke`) và `approval-signer` (xin scope `signer:approve`); luật exchange V2: client gọi exchange phải nằm trong `aud` của subject token (xác minh ở spike M0). `agent:invoke` và `signer:approve` là *optional* client scope của `chat-ui`, không có trong token đăng nhập. Bật *Revoke Refresh Token* (refresh xoay vòng) và đăng ký `post_logout_redirect_uri = BFF_PUBLIC_URL`. M6: exchange thứ ba tới `llm-gateway` (scope `llm:invoke`) **chỉ cho người có role `admin`** (proxy admin API) |
| `agent-service` | confidential, service account, **được phép token-exchange**; cũng là audience | Đổi token `aud=agent-service` của user lấy token theo audience, **chỉ tới `docs-mcp`, `tickets-mcp`, `analytics-mcp` và `llm-gateway`**; **không** được exchange tới `approval-signer` (D13/D15). **Kiểm scope `agent:invoke`** trên token vào (cùng `aud=agent-service`, `azp=chat-ui`); thiếu ⇒ `403 forbidden` |
| `llm-gateway` | bearer-only (audience) | Gateway xác minh danh tính user |
| `docs-mcp`, `tickets-mcp`, `analytics-mcp` | bearer-only (audience) | Resource server |
| `approval-signer` | bearer-only (audience) | Resource server của signer: xác minh token (JWKS, iss, exp) và kiểm `aud` chứa `approval-signer`, scope chứa `signer:approve`, `azp == chat-ui`, `sub == intent.sub` (D13/D15/D16); ngược lại `403 forbidden` |

**Client scopes:** `llm:invoke`, `docs:read`, `tickets:read`, `tickets:write`, `analytics:read`, `agent:invoke`, `signer:approve`.

| Scope | Cấp cho (client) | Ai kiểm | Ghi chú |
|---|---|---|---|
| `llm:invoke`, `docs:read`, `tickets:read`, `tickets:write`, `analytics:read` | `agent-service` (optional scope, xin theo từng exchange) | gateway / từng MCP server | `tickets:write` chỉ cho `prepare_*` + `commit_intent` |
| `agent:invoke` | `chat-ui` (optional; BFF xin khi exchange `aud=agent-service`) | `agent-service` | Audience mapper `agent-service`; không nằm trong token đăng nhập |
| `signer:approve` | `chat-ui` (optional; BFF xin khi exchange `aud=approval-signer`) | `approval-signer` | Audience mapper `approval-signer`; `agent-service` không có scope này nên không xin được |

Cả hai resource server kiểm scope **ngoài** `aud`/`azp` (D16); khớp realm JSON ở `04`. Role `admin` là tên duy nhất của vai trò quản trị.

**Luồng token (D15, thay D13 phần Keycloak; sửa N01/N02):**
1. **Token đăng nhập** (BFF nhận qua Authorization Code + PKCE, client `chat-ui`): `aud=chat-ui`, sống 5 phút, refresh 30 phút (refresh token mã hoá AES-GCM trong session BFF). **Không** gửi cho agent; trình duyệt chỉ có cookie phiên `HttpOnly`.
2. **BFF token-exchange** (RFC 8693, `azp=chat-ui`): (a) -> `aud=agent-service` + scope `agent:invoke`, gửi cho agent trong mỗi request; (b) -> `aud=approval-signer` + scope `signer:approve` (TTL ≤ 300s), chỉ nằm trong **session phía server**, không bao giờ gửi cho agent hay trình duyệt, không cache sang session khác.
3. **`agent-service` exchange** token `aud=agent-service` của nó -> `llm-gateway` + `docs-mcp`/`tickets-mcp`/`analytics-mcp`. **Không** tới `approval-signer` (Keycloak từ chối).
4. **Test bắt buộc (N02):** dùng **chính token agent cầm** (`aud=agent-service`) gọi `approval-signer` -> 401/403; assert token đăng nhập không có `aud ∋ {agent-service, approval-signer}`; `agent-service` exchange tới signer -> Keycloak từ chối.
5. **Mã dùng chung (D16):** `TokenBroker` (adapter `oauth_token_exchange`, `static`) và `TokenVerifier` (adapter `oidc_jwks`) nằm trong `acme_common`; agent, approval-signer, BFF, gateway và MCP dùng chung (§9.2).
**Issuer cố định (dev):** `http://keycloak.acme.local:8080/realms/acme` (so khớp chuỗi chính xác ở mọi resource server). **Token đã exchange** (RFC 8693, agent-service thực hiện cho gateway và 3 MCP, mỗi request lấy một token cho mỗi audience; cache in-process theo khoá `(sub, aud, sorted scopes)`, TTL = `exp − 30s`):
```json
{ "iss": "http://keycloak.acme.local:8080/realms/acme", "sub": "<user uuid>", "aud": "tickets-mcp",
  "azp": "agent-service", "exp": "<= 300s", "scope": "tickets:read tickets:write",
  "dept": ["CS"], "clearance": 1, "roles": ["employee"], "act": {"sub": "agent-service"} }
```
(Nếu Keycloak không phát claim `act` thì dùng `azp` để biết bên nào đang gọi; ghi lại như một giới hạn.)

### 4.1 Phê duyệt ràng buộc giao dịch (D1) — "What You See Is What You Sign"

**Giả định đe doạ:** agent có thể bị chiếm hoặc bị lừa hoàn toàn. Người dùng chỉ thấy dữ liệu do **server (tickets-mcp) tính và ký**; chữ ký phê duyệt gắn với đúng dữ liệu đó. Khoá:

| Khoá ES256 | Giữ bởi | Công khai cho | Dùng để |
|---|---|---|---|
| Khoá intent | `tickets-mcp` (`INTENT_PRIVATE_KEY_PATH`, `INTENT_KEY_ID`) | `approval-signer` (`INTENT_PUBLIC_KEYS_DIR`) | Ký intent JWS |
| Khoá approval | `approval-signer` (`APPROVAL_SIGNER_PRIVATE_KEY_PATH`, `APPROVAL_SIGNER_KEY_ID`) | `tickets-mcp` (`APPROVAL_PUBLIC_KEY_PATH`) | Ký approval token |

Agent và BFF/SPA **không** giữ khoá riêng nào.

**Intent JWS** (header `{"alg":"ES256","typ":"acme-intent+jws","kid":"<INTENT_KEY_ID>"}`), do `tickets-mcp` ký trong `prepare_<op>`:
```json
{ "iss": "tickets-mcp", "aud": "approval-signer",
  "intent_id": "<uuid>", "op": "close_ticket",
  "target": { "ticket_code": "TCK-000123" },
  "before": { "status": "in_progress", "resolution": null },
  "after":  { "status": "closed", "resolution": "<văn bản>" },
  "expected_updated_at": "2026-10-28T08:15:00Z",
  "args_canonical": "<canonical JSON tham số đã chuẩn hoá>",
  "sub": "<user uuid>", "risk_flags": ["possible_downgrade"],
  "iat": 0, "exp": "iat + 300" }
```
`op ∈ {create_ticket, add_comment, update_status, close_ticket}`. tickets-mcp **tự đọc DB** để tính `before`/`after`/`expected_updated_at`; mọi trường hiển thị cho người duyệt lấy từ intent, agent không dựng preview. `intent_sha256 = sha256(canonical_json(payload))` (JCS: khoá sắp xếp, không float). `risk_flags` có thể gồm `possible_downgrade` (D8; chính sách `TAINT_POLICY=warn|block`: `block` -> `prepare_*` trả `forbidden`). Lưu `mcp:tickets:intent:{intent_id}` (§2.1).

**Approval token** (do **approval-signer** ký, không phải LLM, agent hay UI), header `{"alg":"ES256","typ":"acme-approval+jwt","kid":"<APPROVAL_SIGNER_KEY_ID>"}`:
```json
{ "iss": "acme-approval", "aud": "tickets-mcp", "sub": "<user uuid>",
  "intent_id": "<uuid>", "intent_sha256": "<sha256 canonical payload của intent>",
  "jti": "<uuid>", "iat": 0, "exp": "iat + 120" }
```
**API của approval-signer** (đều yêu cầu `Authorization: Bearer <token đã exchange cho approval-signer, D13>`; signer verify bằng JWKS, kiểm `iss`, `exp`, `aud` chứa `approval-signer`, `azp == chat-ui` và `sub == intent.sub`; sai -> `403 forbidden`; token của agent (`azp=agent-service`) bị từ chối):
- `POST /v1/intents/verify {intent_jws}` -> xác minh chữ ký (public key MCP mount sẵn), `exp`, `sub == token.sub` -> trả **render model** `{intent_id, op, target, before, after, risk_flags, expires_at, intent_sha256, server_time, display: {title, risk, display_fields, diff}}` (chi tiết `05` mục 5.3; BFF làm phẳng `display` khi trả cho SPA). `server_time` = giờ máy chủ signer (RFC 3339) để SPA bù lệch đồng hồ. `display_fields[] = {path, label, kind, before, after, changed, sensitive}` với `kind ∈ text|longtext|enum|datetime|ticket_ref` (**tập chuẩn duy nhất, định nghĩa ở `05` mục 5.3**; `07` mục 3.6 render đúng tập này). `display_fields` phủ **toàn bộ** `args_canonical` + `before/after` (N03); có trường không hiển thị được -> `422 intent_unrenderable` (cả `/v1/intents/verify` lẫn `/v1/approvals`). SPA chỉ render từ đây (kiểu lạ -> không cho bấm Duyệt; ký tự bidi/điều khiển hiển thị dạng escape).
- `POST /v1/approvals {intent_jws}` -> như trên, rồi ký approval token. Signer không có state/Redis; chống replay do tickets-mcp đảm nhiệm.

**Luồng ghi (thay hoàn toàn luồng cũ ký `args`):**
1. Agent gọi `prepare_<op>(args)` trên tickets-mcp (scope `tickets:write`, **không** đổi dữ liệu) -> nhận `intent_jws`.
2. Agent `interrupt({intent_jws})`.
3. BFF (`POST /api/intents/verify`) gọi `approval-signer /v1/intents/verify` -> SPA render thẻ duyệt.
4. User bấm Duyệt -> BFF (`POST /api/approvals`) gọi `approval-signer /v1/approvals` -> `approval_token` (không trả về trình duyệt).
5. BFF resume graph `Command(resume={decision:"approve", approval_token})`; agent gọi `commit_intent(intent_id, approval_token)`.
6. tickets-mcp kiểm: chữ ký approval, `aud`, `exp`, `sub == caller.sub`, intent tồn tại + `sha256` khớp `intent_sha256` + `status=pending`, `jti` `SET NX` (replay -> `approval_replayed`), rồi thực thi trong một transaction với `expected_updated_at` (lệch -> `conflict`), ghi `ticket_events` + `tool_audit` cùng transaction, đặt intent `status=committed`; trả `approval_jti`.
7. **Sửa (edit):** SPA/BFF gửi args mới cho agent -> agent gọi lại `prepare_*` -> intent mới. Không bao giờ ký args do UI/agent tự dựng. **Từ chối:** intent hết TTL tự huỷ.
8. Các tool ghi trực tiếp kiểu cũ (nhận `approval_token` theo `args`) **không còn**: tool ghi = cặp `prepare_<op>` + `commit_intent`.

**Xoay khoá (D14):** khoá ES256 (intent, approval) xoay với overlap 15 phút; JWKS/thư mục khoá công khai công bố cả `kid` cũ và mới trong thời gian overlap.

**Rủi ro còn lại (ghi rõ):** BFF bị chiếm có thể xin chữ ký cho intent của chính user đang đăng nhập (sub khớp). Giảm thiểu: BFF tối giản, token không xuống trình duyệt, CSP chặt từ M1; và tuỳ chọn step-up (WebAuthn/CIBA) cho thao tác rủi ro cao (sau v1.0).

**Gateway nhận danh tính user:** agent gọi gateway với `Authorization: Bearer <API key của agent-service>` và `X-Acme-User-Token: <JWT aud=llm-gateway>`. Gateway chỉ tin header này khi key có `trust_end_user_token = true`. Khi đó chi phí, budget và chính sách PII tính theo `dept` của user.

## 5. Model alias (`config/models.yaml`)
```yaml
aliases:
  acme-fast:  { chain: [anthropic/claude-haiku-5-5, gemini/gemini-2.5-flash-lite], timeout_s: 30 }
  acme-smart: { chain: [anthropic/claude-sonnet-5-5, gemini/gemini-3.1-pro-preview], timeout_s: 90 }
  acme-auto:  { router: complexity_v1, simple: acme-fast, complex: acme-smart }
  acme-embed: { chain: [sidecar/embed] }   # (D14: thay local/bge-m3) gateway chuyển tiếp tới policy-sidecar /v1/embed; không có runtime embedding trong gateway
  acme-judge: { chain: [gemini/gemini-3.1-pro-preview, anthropic/claude-sonnet-5-5], timeout_s: 90 }   # KHÁC họ với model chính của agent (Claude) để giảm thiên vị tự chấm; chỉ key phòng EVAL
```
(Model ID chính xác cần đối chiếu với docs của provider khi code.)

## 6. Mã lỗi, header, endpoint

### 6.1 Mã lỗi gateway (format lỗi OpenAI `{"error":{"message","type","code"}}`)

| HTTP | `code` | Khi nào |
|---|---|---|
| 400 | `invalid_request` | Body sai schema, `n>1`, ảnh URL ngoài |
| 401 | `invalid_api_key` | Sai định dạng, sai HMAC, không tồn tại |
| 401 | `key_revoked` / `key_expired` | |
| 401 | `invalid_end_user_token` | Header user token sai hoặc hết hạn |
| 403 | `forbidden` | Admin API thiếu role; xem request của key khác |
| 403 | `model_not_allowed` | Alias không nằm trong `allowed_models` (kể cả `acme-judge` với key không thuộc EVAL) |
| 429 | `rate_limit_requests` / `rate_limit_tokens` / `concurrency_limit` | Kèm `Retry-After` |
| 402 | `budget_exceeded` | Hết budget của key hoặc phòng ban |
| 400 | `pii_blocked` | Chính sách `block` và phát hiện PII |
| 400 | `prompt_injection_detected` | Guard chặn (khi bật chế độ block) |
| 409 | `idempotency_conflict` | `Idempotency-Key` trùng với request khác nội dung/đang chạy |
| 413 | `request_too_large` | Body vượt giới hạn byte (4 MiB) |
| 413 | `context_too_large` | Vượt `max_input_tokens` (giới hạn token) |
| 500 | `internal_error` | Lỗi không lường trước (không lộ chi tiết) |
| 502 | `all_providers_failed` | Hết chuỗi fallback |
| 503 | `provider_circuit_open` | Mọi provider trong chuỗi đều đang mở breaker |
| 503 | `service_unavailable` | Degraded Redis quá `GW_DEGRADED_MAX_S` hoặc alias không phải `acme-fast` khi degraded; PG/Redis đều lỗi; policy-sidecar lỗi với `guard: fail_closed` |

### 6.2 Header, endpoint

**Request header (tuỳ chọn):** `Idempotency-Key`; `X-Acme-Client-Request-Id` (gateway log và **trả lại** trong response header cùng tên); `traceparent` (W3C, truyền xuyên suốt agent -> gateway -> MCP -> Langfuse, ghi vào `usage_events`/`audit_log.details`).

**Response header luôn có:** `x-acme-request-id`, `x-acme-provider`, `x-acme-model`, `x-acme-fallbacks`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `X-Acme-Client-Request-Id` (nếu client gửi). **`x-acme-cache: miss|exact|semantic` chỉ trả cho key `expose_debug = true`** (admin/EVAL; D4). **`x-acme-cost-usd` chỉ có ở non-stream** (khi stream chưa biết chi phí lúc gửi header; không dựa vào header). Header tuỳ chọn: `x-acme-guard`, `x-acme-degraded`, `x-acme-route-reason`, `x-acme-budget-warning`, `x-acme-ignored-params`.

**Chi phí khi stream:** chunk usage cuối (chunk có `usage`) mang thêm object mở rộng:
```json
"x_acme": {"request_id":"<uuid>","cost_usd":0.001234,"fallbacks":0,"provider":"anthropic","model":"claude-sonnet-5-5"}
```
(trường `"cache":"miss|exact|semantic"` chỉ có khi key `expose_debug = true`) và endpoint `GET /v1/requests/{request_id}` (Bearer API key; **chỉ key sở hữu request** được xem, key khác -> 403 `forbidden`) trả cùng thông tin. Hàm `make_chat_model(role)` của agent đọc `x_acme` nếu có, fallback gọi endpoint.

**Admin API của gateway (D14; chi tiết ở `01-gateway.md` §14, role `admin`, `Cache-Control: no-store`, mọi lời gọi ghi `EventSink.append(sync=True)`):**

| Method | Path | Role | Mục đích |
|---|---|---|---|
| POST | `/admin/cache/warmup` | admin | Sinh bản nháp câu trả lời cho warm-up semantic cache; **không ghi cache** |
| POST | `/admin/cache/faq` | admin | Nạp FAQ đã duyệt (`source ∈ {faq_approved, admin_warmup}`); đường ghi duy nhất vào semantic cache |
| GET | `/admin/cache/entries` | admin, auditor | Liệt kê metadata entry (không trả vector) |
| DELETE | `/admin/cache/entries/{id}` | admin | Xoá một entry |
| POST | `/admin/cache/purge` | admin | Xoá theo `alias` hoặc `scope_hash` |
| POST/PATCH | `/admin/keys` | admin | Tạo/sửa key, gồm cờ `expose_debug` |

**Metric mới (D14; bảng đầy đủ ở 01 §7, 04 §6):** `gateway_sidecar_duration_seconds`, `gateway_sidecar_errors_total`, `gateway_sidecar_fail_policy_total`, `gateway_cache_ineligible_total`, `gw_degraded_overspend_max_usd`, `gateway_audit_anchor_age_seconds`, `gateway_audit_chain_verify_failed`, `approval_signer_requests_total{result}`, `approval_signer_sign_ms`, `mcp_approval_rejected_total{reason}`.

**Endpoint BFF (D15/D16; cổng 8300; chi tiết `07` mục 2.6):** `GET /auth/login`, `GET /auth/callback` (cookie `__Host-login` SameSite=Lax, chỉ cho callback), `POST /auth/logout`, `GET /api/me`, `POST /api/chat` (SSE; `thread_id=null` tạo thread ngầm, event `thread`), `POST /api/resume` (edit/reject/refresh; `approve` không đi qua đây), `GET /api/threads`, `GET /api/threads/{id}/messages`, `DELETE /api/threads/{id}`, `POST /api/intents/verify`, `POST /api/approvals` (phải kèm `intent_sha256` đã verify; trả SSE của lượt resume), `GET /api/requests/{request_id}`, `GET /healthz`, `GET /readyz`, `GET /metrics`; M6: `/api/admin/*` (role `admin`).

**Endpoint agent bổ sung (D16):** `GET /v1/requests/{request_id}` (agent giữ API key sở hữu request, kiểm request thuộc thread của `sub` rồi gọi `GET /v1/requests/{id}` của gateway) phục vụ `GET /api/requests/{id}`; `POST /v1/internal/evict` (`sub` lấy từ token Bearer, không nhận tham số). Chi tiết `03` mục 1.3.

### 6.3 Mã lỗi tool MCP (chuẩn hoá; trả trong kết quả tool lỗi, trường `code`; approval-signer dùng cùng mã trong body lỗi HTTP)
`unauthorized`, `forbidden`, `not_found`, `invalid_argument`, `rate_limited`, `approval_required`, `approval_invalid`, `approval_expired`, `approval_mismatch`, `approval_replayed`, **`intent_not_found`** (không có intent, đã `committed`/hết TTL bị xoá), **`intent_expired`** (quá `exp` của intent), **`intent_mismatch`** (`sha256` không khớp `intent_sha256`, chữ ký intent sai, hoặc `sub` của intent khác `sub` của caller), **`intent_unrenderable`** (422; signer: intent có trường không hiển thị được trong `display_fields`, D15/N03), `conflict` (optimistic concurrency, `expected_updated_at` lệch), `query_rejected`, `query_timeout`, `upstream_unavailable`.

### 6.4 Lỗi BFF (D15/D16; JSON `{"error":{"code","message","retryable","request_id"}}`, không lộ chi tiết; mọi response có `X-Request-Id`)
| HTTP | `code` | Khi nào |
|---|---|---|
| 400 | `invalid_request` | Body sai schema; `type=approve` ở `/api/resume` |
| 401 | `session_expired` | Không có cookie phiên, phiên hết idle (30 phút)/tuyệt đối (8 giờ), refresh thất bại; SPA chuyển tới `/auth/login` |
| 403 | `csrf_failed` | Request đổi trạng thái thiếu/sai `X-CSRF-Token` hoặc `Origin` |
| 403 | `forbidden` | Thiếu role (vd `/api/admin/*` cần role `admin`) hoặc signer trả `forbidden` |
| 404 | `not_found` | Thread/request không tồn tại hoặc không thuộc người dùng |
| 404 | `interrupt_not_found` | Không có `pend`/khác thread; SPA gọi lại `GET /messages` |
| 409 | `conflict` | Run khác đang chạy / interrupt không khớp |
| 410 | `intent_expired` | Chuyển tiếp từ signer |
| 413 | `request_too_large` | Body > 64 KiB |
| 422 | `intent_unrenderable` | Chuyển tiếp từ signer; SPA không cho Duyệt |
| 422 | `intent_mismatch` | Chuyển tiếp từ signer, hoặc `intent_sha256` gửi lên khác thẻ đã verify |
| 429 | `rate_limited` | Vượt hạn mức theo phiên/IP/người dùng (+ `Retry-After`) |
| 502 | `upstream_unavailable` | `agent`/`approval-signer`/Keycloak lỗi (503 khi Redis lỗi, fail-closed) |
| SSE `error` | `upstream_timeout` (`retryable=true`) | Vượt `BFF_STREAM_MAX_S`/`BFF_STREAM_IDLE_S` |

Mã nhận từ agent qua SSE (`budget_exceeded`, `provider_unavailable`, ...) được chuyển nguyên `code`/`retryable`.

## 7. Biến môi trường

**Quy ước secret:** mọi biến nhạy cảm (mật khẩu, key, secret, URL có mật khẩu) hỗ trợ dạng `<BIẾN>_FILE` (đọc nội dung file, vd Docker secret); có cả hai thì `_FILE` thắng. Không secret nào nằm trong image; `.env` đã gitignore. Mật khẩu Redis nằm ngoài URL (`*_REDIS_PASSWORD_FILE`). Production: secret manager (Vault/SOPS) ở M7.

**Chung (mọi service):**

| Biến | Giá trị / ghi chú |
|---|---|
| `ACME_ENV` | `dev\|test\|bench\|eval` (`eval` mới cho phép adapter `permissive`) |
| `LOG_LEVEL`, `OTEL_EXPORTER_OTLP_ENDPOINT` | |
| `KEYCLOAK_ISSUER` | `http://keycloak.acme.local:8080/realms/acme` (cố định) |
| `METRICS_TOKEN` | Bearer cho `/metrics` của service đó |

**Theo service:**

| Service | Biến |
|---|---|
| gateway | `GW_DATABASE_URL`, `GW_REDIS_STATE_URL`, `GW_REDIS_CACHE_URL` (user `gateway`), `GW_KEY_PEPPER` (>= 32 byte), `GW_KEY_PEPPER_PREV` (tuỳ chọn), `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GW_SIDECAR_URL=http://policy-sidecar:8010`, `SIDECAR_TOKEN`, `SIDECAR_TOKEN_PREV` (tuỳ chọn, xoay token), `GW_SIDECAR_TIMEOUT_MS`, `GW_GUARD_FAIL_POLICY=fail_open\|fail_closed`, `GW_NER_FAIL_POLICY=skip_on_error`, `GW_WORKERS`, `GW_INSTANCES`, `GW_DEGRADED_MAX_S=600`, `AUDIT_HMAC_KEY`, `AUDIT_HMAC_KEY_ID`, `AUDIT_ANCHOR_DIR` (dev) / `AUDIT_ANCHOR_BUCKET` (prod), `GW_PROVIDER_OVERRIDE=mock` (factory thay MỌI phần tử của mọi chain bằng adapter `mock`, giữ tên model gốc để tính giá; không `if` trong business code), `GW_FEATURES=auth,ratelimit,budget,pii,guard,cache,router` (ablation; thứ tự stage cố định, `router` trước `cache`; `auth` chỉ tắt được khi `ACME_ENV=bench`), `GW_PII_STRICT`, `METRICS_TOKEN` |
| policy-sidecar | `SIDECAR_PORT=8010`, `SIDECAR_TOKEN` (bearer nội bộ), `SIDECAR_TOKEN_PREV` (tuỳ chọn, chấp nhận token cũ khi xoay), `MODELS_LOCK_PATH=/app/models.lock`, `MODELS_LOCK_SHA256` (hash của `models.lock`; lệch -> từ chối khởi động), `SIDECAR_MODELS_DIR`, `SIDECAR_EMBED_ENABLED`, `SIDECAR_GUARD_ENABLED`, `SIDECAR_NER_ENABLED`, `SIDECAR_WORKERS`, `METRICS_TOKEN`. Không có khoá provider, DB hay Redis |
| approval-signer | `SIGNER_PORT=8310`, `SIGNER_AUDIENCE=approval-signer`, `SIGNER_ALLOWED_AZP` (mặc định `chat-ui`; D13/D15: signer kiểm `aud` + `azp == chat-ui` + `sub == intent.sub`), `APPROVAL_SIGNER_PRIVATE_KEY_PATH`, `APPROVAL_SIGNER_KEY_ID`, `INTENT_PUBLIC_KEYS_DIR` (khoá công khai intent của tickets-mcp, mount read-only), `APPROVAL_TTL_S=120`, `METRICS_TOKEN`. Không có DB, Redis hay secret nào khác |
| agent | `AGENT_GATEWAY_URL=http://gateway:8000/v1`, `AGENT_GATEWAY_KEY`, `AGENT_KC_CLIENT_ID`, `AGENT_KC_CLIENT_SECRET`, `AGENT_DATABASE_URL` (`ag_app`), `AGENT_DATABASE_OWNER_URL` (`ag_owner`, chỉ job migrate/setup), `MCP_DOCS_URL=http://docs-mcp:8101/mcp`, `MCP_TICKETS_URL`, `MCP_ANALYTICS_URL`, `AGENT_MAX_TOOL_CALLS_TURN`, `AGENT_MAX_TURN_COST_USD`, `AGENT_RECURSION_LIMIT`, `AGENT_CONF_MIN`, `AGENT_CHECKPOINT_ENCRYPTION_KEY` (**bắt buộc** ngoài `ACME_ENV=test`), `AGENT_THREAD_RETENTION_DAYS=30`, `LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY` (profile `obs`), `LANGFUSE_CAPTURE_CONTENT=false` (mặc định, chỉ metadata), `METRICS_TOKEN`. Agent **không** có `APPROVAL_SIGNER_URL` và không được cấp quyền exchange tới `approval-signer` (D13) |
| bff | `BFF_PUBLIC_URL`, `BFF_SESSION_KEY` (khoá AES-GCM mã hoá refresh token), `BFF_OIDC_CLIENT_SECRET` (client `chat-ui`), `BFF_AGENT_URL=http://agent:8200`, `BFF_SIGNER_URL=http://approval-signer:8310`, `BFF_REDIS_URL=redis://bff@redis-state:6379/0`, `BFF_SIGNER_TOKEN_TTL_S=300` (≤ 300), `BFF_SESSION_IDLE_S=1800`, `BFF_SESSION_ABS_S=28800`, `BFF_STREAM_MAX_S=300`, `BFF_STREAM_IDLE_S=45`, `BFF_LINK_ALLOWLIST` (host cho phép trong markdown; mặc định rỗng), `BFF_GATEWAY_URL` (M6, proxy admin), `BFF_COOKIE_INSECURE_DEV=false` (chỉ `ACME_ENV=dev`), `BFF_TRUSTED_PROXY=false`, `REDIS_BFF_PASSWORD` (user `bff` trên redis-state, `~bff:sess:*`), `METRICS_TOKEN`. BFF exchange lấy `aud=agent-service` và `aud=approval-signer`; token signer chỉ ở session server. **Không có** khoá ký (D15) |
| docs-mcp | `MCP_AUDIENCE=docs-mcp`, `MCP_HOST` (tên adapter `mcp_sdk\|fastmcp`), `MCP_PORT=8101`, `MCP_PUBLIC_URL`, `MCP_DATABASE_URL` (`kn_app`), `MCP_REDIS_URL` (user `docs`; gồm taint), `DOCS_GATEWAY_URL`, `DOCS_GATEWAY_KEY` (key `owner_type=service`, `allowed_models={acme-embed}`, PII `allow`), `DOCS_RERANK`, `DOCS_RETRIEVER`, `MCP_TAINT_TTL_S=1800`, `MCP_ALLOWED_AZP`, `MCP_ALLOWED_ORIGINS`, `MCP_RL_CAPACITY`, `MCP_RL_REFILL_PER_S`, `MCP_MAX_OUTPUT_BYTES`, `MCP_AUDIT_DATABASE_URL`, `AUDIT_HMAC_KEY`, `AUDIT_HMAC_KEY_ID`, `METRICS_TOKEN` |
| tickets-mcp | như docs-mcp (không có `DOCS_*`, `MCP_TAINT_TTL_S`), `MCP_AUDIENCE=tickets-mcp`, `MCP_PORT=8102`, `MCP_DATABASE_URL` (`tk_app`), `MCP_REDIS_URL` (user `tickets`), `INTENT_PRIVATE_KEY_PATH`, `INTENT_KEY_ID`, `INTENT_TTL_S=300` (khoá Redis TTL = `INTENT_TTL_S`+30), `APPROVAL_PUBLIC_KEY_PATH`, `TAINT_POLICY=warn\|block`, `TICKETS_REPOSITORY`, `INTENT_ISSUER` (`es256_jws`), `APPROVAL_VERIFIER` (`es256_jwt`), `AUDIT_HMAC_KEY`, `AUDIT_ANCHOR_DIR`. Adapter `permissive` (của `IntentIssuer`/`ApprovalVerifier`) chỉ khi `ACME_ENV=eval`, nếu không factory raise lúc khởi động; WARNING mỗi lần dùng |
| analytics-mcp | như docs-mcp (không có `DOCS_*`), `MCP_AUDIENCE=analytics-mcp`, `MCP_PORT=8103`, `MCP_DATABASE_URL` (`an_reader`), `MCP_REDIS_URL` (user `analytics`). *Tuỳ chọn sau v1.0:* `ANALYTICS_ENABLE_RAW_SQL`, `ANALYTICS_CTX_HMAC_KEY` (>= 32 byte) |
| redis | `REDIS_GATEWAY_PASSWORD`, `REDIS_TICKETS_PASSWORD`, `REDIS_DOCS_PASSWORD`, `REDIS_ANALYTICS_PASSWORD`, `REDIS_HEALTH_PASSWORD`, `REDIS_OPS_PASSWORD` (đều qua `_FILE`) |
| keycloak | `KC_HOSTNAME=http://keycloak.acme.local:8080`, `KC_DB_URL` (`kc_app`) |
| TLS (chỉ bật ở M7, D14) | Mỗi service nhóm `<SVC>_TLS_CERT`, `<SVC>_TLS_KEY`, `<SVC>_TLS_CA` (đường dẫn file; qua `_FILE`/mount read-only); dev để trống |
| ngân sách EVAL (D14) | Phòng `EVAL`: trần cứng 160 USD/tháng (dự kiến ~130); key `eval-regression` cho nightly regression (§3.1) |

### 7.1 Supply chain cho model: `models.lock` (D3)

`models.lock` nằm ở gốc repo, được review như code. Mỗi model một mục; thiếu hoặc lệch hash -> build/CI thất bại và `policy-sidecar` **từ chối khởi động**.
```toml
[[model]]
name      = "bge-m3"
repo      = "BAAI/bge-m3"
revision  = "<commit sha 40 ký tự>"        # cố định, không dùng tên nhánh
license   = "MIT"
files     = [ { path = "onnx/model_int8.onnx", sha256 = "<64 hex>" } ]   # file đã convert/quantize do CI tạo
```
Quy tắc: (1) tải bằng `huggingface_hub` với `revision` cố định, `trust_remote_code=False`, chỉ nhận `*.safetensors`/`*.onnx` (không pickle); (2) script convert/quantize nằm trong repo, chạy ở CI và xuất hash ghi vào `models.lock`; (3) sidecar verify sha256 của mọi file lúc khởi động; (4) ghi license từng model: Prompt Guard 2 (Llama license, cần kiểm điều khoản), bge-m3 (MIT), underthesea (kiểm tra GPL trước khi phân phối image). Image sidecar không chứa token HF. Parity ingest/query: so recall@k fp32 vs int8 trên tập dev (Δ ≤ 1 điểm), không so cosine từng vector.

---

## 8. Luồng tổng: "Đóng ticket TCK-000123 giúp tôi"

```mermaid
sequenceDiagram
  autonumber
  actor U as Nhân viên (CS)
  participant SPA as Trình duyệt (SPA React)
  participant UI as bff
  participant KC as Keycloak
  participant AG as agent (LangGraph)
  participant GW as gateway
  participant LLM as Claude/Gemini
  participant TK as tickets-mcp
  participant SG as approval-signer
  participant RS as redis-state
  participant PG as Postgres
  U->>SPA: mở web, bấm đăng nhập
  SPA->>UI: GET /auth/login (OIDC code + PKCE)
  UI->>KC: auth code → token đăng nhập (aud=chat-ui); lưu session Redis bff:sess:{sid}
  UI-->>SPA: Set-Cookie __Host-sid (HttpOnly); không có token trong JS
  U->>SPA: "Đóng ticket TCK-000123, đã xử lý xong"
  SPA->>UI: POST /api/chat (cookie + X-CSRF-Token)
  UI->>KC: token-exchange → aud=agent-service
  UI->>AG: POST /threads/{id}/runs (Bearer aud=agent-service)
  AG->>KC: token-exchange (subject aud=agent-service) → aud=llm-gateway, aud=tickets-mcp
  AG->>GW: chat.completions (acme-fast, router) + X-Acme-User-Token
  GW->>LLM: request đã mask PII
  LLM-->>GW: {"route":"ticket"}
  GW-->>AG: response (+ x-acme-cost-usd non-stream; stream: x_acme ở chunk cuối)
  AG->>GW: ticket_agent (acme-smart, tools=tickets-mcp)
  GW-->>AG: tool_call prepare_close_ticket(code=TCK-000123, resolution=...)
  AG->>TK: tools/call prepare_close_ticket + Bearer(aud=tickets-mcp)
  TK->>TK: verify JWT user (aud, iss, exp, scope tickets:write)
  TK->>PG: SET LOCAL app.*; SELECT ticket (RLS) → before, updated_at
  TK->>RS: GET mcp:taint:{sub} (so với classification ticket)
  TK->>TK: tính intent {before, after, expected_updated_at, risk_flags}; ký JWS (khoá intent)
  TK->>RS: HSET mcp:tickets:intent:{intent_id} {sha256, sub, pending} EX 330
  TK-->>AG: {intent_jws} (chưa đổi dữ liệu)
  AG-->>UI: interrupt {intent_jws} (SSE)
  UI->>KC: token-exchange (subject=token đăng nhập) → aud=approval-signer (azp=chat-ui; giữ trong session server, agent không thấy)
  UI->>SG: POST /v1/intents/verify {intent_jws} + token signer
  SG->>SG: verify aud, azp == chat-ui, chữ ký MCP, exp, sub == intent.sub, display_fields phủ đủ
  SG-->>UI: render model {before, after, display_fields, risk_flags}
  UI-->>SPA: render model (SSE/JSON)
  SPA-->>U: Thẻ xác nhận (chỉ render từ render model) [Duyệt][Sửa][Từ chối]
  U->>SPA: Duyệt
  SPA->>UI: POST /api/approvals (cookie + CSRF)
  UI->>SG: POST /v1/approvals {intent_jws} + token signer
  SG->>SG: verify token (JWKS, aud, azp), intent chưa hết hạn
  SG-->>UI: approval_token (ES256; intent_id, intent_sha256, jti, exp 120s)
  UI->>AG: Command(resume={approve, approval_token})
  AG->>TK: tools/call commit_intent(intent_id, approval_token) + Bearer(aud=tickets-mcp)
  TK->>TK: verify approval (chữ ký signer, aud, exp, sub == caller.sub)
  TK->>RS: kiểm intent: tồn tại, sha256 khớp, status=pending
  TK->>RS: SET mcp:tickets:jti:{jti} NX EX 180 (chống replay)
  TK->>PG: BEGIN; UPDATE tickets ... WHERE updated_at = expected (RLS); INSERT ticket_events; INSERT tool_audit; COMMIT
  TK->>RS: intent status = committed
  TK-->>AG: {ok, ticket, approval_jti}
  AG->>GW: final answer (acme-fast)
  AG-->>UI: "Đã đóng TCK-000123" + chi phí
  UI-->>SPA: SSE stream về trình duyệt
```
Nhánh phụ: **Sửa** -> UI gửi tham số mới cho agent -> agent gọi lại `prepare_close_ticket` -> intent mới (lặp lại từ bước `prepare`). **Từ chối** -> graph quay lại `ticket_agent`, intent tự hết hạn sau 300s (khoá Redis dọn sau 330s). **Agent tự xin approval** (gọi `/v1/approvals` bằng chính token `aud=agent-service` mình cầm) -> `401/403` (D13/D15). **TOCTOU** (ticket đổi sau khi duyệt) -> `UPDATE` 0 dòng -> `conflict`, rollback, không ghi audit thành công. **Agent độc đổi tham số/ticket sau duyệt** -> `intent_mismatch` (hash không khớp) hoặc `intent_not_found`.

## 9. Kiến trúc code: Ports & Adapters (BẮT BUỘC)

> Mục tiêu: thêm vendor/biến thể mới = **thêm** 1 file adapter + 1 dòng registry + 1 block config, **không sửa** service/route/business logic/test nghiệp vụ.

### 9.1 Quy tắc
1. **Port đặt tên theo năng lực, không theo vendor.** `ChatProvider`, không phải `ClaudeClient`. Method là động từ của năng lực (`complete`, `stream`, `embed`, `search`, `verify`...), chỉ khai báo những method mà consumer thực sự gọi.
2. **Python: mặc định `abc.ABC` + `@abstractmethod`**, adapter và fake **kế thừa tường minh** (thiếu method thì lỗi ngay lúc khởi tạo). Chỉ dùng `typing.Protocol` để type hint object của thư viện bên thứ ba.
3. **Kiểu dữ liệu và lỗi trung lập** ở biên: `ChatRequest`, `ChatChunk`, `Usage`, `Principal`, `RetrievedChunk`, `Intent`; `ProviderError(kind, retryable)`, `TokenInvalid`... Adapter dịch exception của vendor sang các lỗi này. Message lỗi **không** chứa URL, header, key hay nội dung người dùng.
4. **Tách file.** `ports/` (ABC + neutral types + errors), `adapters/<vendor>.py` (mỗi vendor một file), `factory.py` (registry). Module trong `ports/` không import vendor nào.
5. **Factory dùng registry dict + lazy import**, không dùng chuỗi `if/elif`. Vendor được chọn bằng config. Tên lạ thì raise `XxxNotConfigured` kèm danh sách tên hợp lệ:
   ```python
   _REGISTRY: dict[str, Callable[[Settings], ChatProvider]] = {
       "anthropic": _load_anthropic,   # lazy: from .adapters.anthropic import AnthropicProvider
       "gemini":    _load_gemini,
       "mock":      _load_mock,
   }
   def build_provider(name: str, settings: Settings) -> ChatProvider:
       try:
           loader = _REGISTRY[name]
       except KeyError:
           raise ProviderNotConfigured(f"unknown provider; known: {sorted(_REGISTRY)}") from None
       return loader(settings)
   ```
   Config riêng của từng vendor nằm trong block mang tên vendor (`providers.anthropic.*`). Factory được nối vào DI (`Depends`) để test override ở đúng một chỗ.
6. **Mối quan tâm cắt ngang dùng decorator cùng port:** `RetryingProvider(inner)`, `CircuitBreakingProvider(inner, breaker)`, `FallbackProvider([a, b])`, `MeteredProvider(inner)` (metrics/trace, chỉ ghi metadata, không ghi payload). Factory bọc sẵn, nên vendor mới được hưởng các lớp này mà không phải viết thêm.
7. **Plumbing dùng chung bằng composition:** `RetryingHttpClient` (timeout → phân loại `timeout|connection|http_<status>` → 4xx khác 429 thì fail fast → backoff có jitter → giới hạn số lần thử). Adapter giữ một instance chứ không kế thừa. Độ sâu kế thừa tối đa: port ABC → (base trừu tượng dùng chung, khi có ≥2 adapter chung luồng) → adapter.
8. **Business logic chỉ import port và factory.** Kiểm tra bằng leak-grep trong CI (cả hai lệnh phải **không có kết quả nào**):
   `grep -rniE "anthropic|gemini|google|keycloak|presidio|underthesea|pgvector|qdrant|fastmcp|langfuse" packages/*/src --include=*.py | grep -vE "/adapters/|factory\.py|settings\.py"`
   (gateway không nạp model nặng, D2): `grep -rniE "onnxruntime|torch|tokenizers|transformers|sentence_transformers|huggingface_hub" packages/gateway/src --include=*.py`,
   và (frontend, D15; chỉ `src/api/client.ts` được dùng `fetch`/SSE): `grep -rnE "\bfetch\(|XMLHttpRequest|EventSource|fetch-event-source|axios|keycloak-js|oidc-client" web/src --include=*.ts --include=*.tsx | grep -vE "src/api/client\.ts|\.test\.tsx?$"`.
9. **Test:** `Fake<Port>` trong `packages/common/testing/` kế thừa port (gồm `FakeClock`). Test nghiệp vụ dùng fake; test HTTP chỉ dành cho chính adapter. Mỗi factory có một test (tên đúng thì chạy, tên lạ thì báo lỗi). Không test cơ chế của ngôn ngữ.
10. **Không trừu tượng hoá quá mức (D11).** Mỗi port phải có (a) adapter thứ hai thật hoặc đã lên kế hoạch, hoặc (b) fake thay thế I/O, hoặc (c) có tác dụng chặn tên vendor lan vào business logic. Thứ không đạt thì là **module thường**. **Không bọc:** Postgres/SQLAlchemy, client Redis, FastAPI, chính LangGraph, `BaseCheckpointSaver`, giao thức OpenAI-compatible giữa agent và gateway, OpenTelemetry. Không DI container, không plugin auto-discovery.
11. **Adapter `permissive`** (bỏ qua kiểm tra approval/intent, phục vụ ablation) chỉ được tạo khi `ACME_ENV=eval`; factory raise lúc khởi động nếu env khác.

### 9.2 Bảng port của hệ thống (khớp D11)

| Service | Port (ABC) | Method chính | Adapter v1 | Adapter mở rộng sau | Decorator |
|---|---|---|---|---|---|
| gateway | `ChatProvider` | `complete(req)`, `stream(req)` | `anthropic`, `gemini`, `mock` | openai, vertex, bedrock, vllm/ollama (on-prem) | Retrying, CircuitBreaking, Fallback, Metered |
| gateway, policy-sidecar | `Embedder` | `embed(texts)` | gateway: `sidecar_http`; sidecar: `bge_m3_onnx`; test: `fake` | gemini-embedding, vietnamese_embedding | Metered |
| gateway, policy-sidecar | `PiiDetector` | `detect(text) -> list[PiiSpan]` | gateway: `regex_vi` (thuần Python), `sidecar_ner` (gọi `/v1/pii/ner`, `skip_on_error`); policy-sidecar: `underthesea_ner` (D14; adapter nằm trong `packages/policy_sidecar`) | gliner; `presidio_vi` chỉ là baseline ngoài tuỳ chọn | Composite(regex → NER) |
| gateway, policy-sidecar | `InjectionGuard` | `score(texts) -> list[float]` | gateway: `sidecar_http` (fail-policy `fail_open\|fail_closed`), `noop`; sidecar: `prompt_guard2_onnx` | llm_guard, azure prompt shields | Metered |
| gateway | `ResponseCache` | `get(key_ctx, req)`, `put(...)` | `redis_exact`, `redis_semantic`, `null` | — | Composite(exact → semantic) |
| gateway | `ModelRouter` | `route(req, principal) -> RouteDecision` | `static`, `complexity_v1` | routellm, classifier | — |
| gateway, common | `RateLimiter` | `reserve(...)`, `settle(...)`, `acquire_slot(key_id, max)`, `release_slot(key_id)`; MCP dùng cho rate limit tool theo user | `redis_token_bucket`, `in_memory` (degraded, D5) | — | — |
| gateway | `SpendTracker` | `check(...)`, `record(...)` | `redis_pg` | — | — |
| gateway | `CircuitBreaker` | `allow(p)`, `on_result(p, outcome)` | `redis`, `in_memory` (degraded) | — | — |
| gateway | `KeyStore` | `lookup(prefix)`, `create`, `revoke` | `pg_redis_cached` | vault | — |
| gateway, mcp (all) | **`EventSink`** (gộp `UsageSink` + `AuditSink` + `ToolAuditSink`) | `append(record, sync=False)` (usage / audit; hash-chain HMAC; `sync=True` ghi đồng bộ cho audit, cùng transaction khi có), `flush()` (đẩy batch usage). Không có `append_sync` riêng (D14) | `postgres`, `json_log` | kafka, OTel logs | — |
| common (job anchor hằng giờ; gateway, tickets-mcp) | **`AnchorStore`** (D14; tên thống nhất, không đặt tên theo vendor hay "Audit...Sink") | `put(anchor)`, `latest()` | `file_append_only` (dev), `s3_object_lock` (prod, sau) | — | — |
| gateway | `PipelineStage` | `async __call__(ctx, call_next)` | auth, ratelimit, budget, pii, guard, cache, router | — | Thứ tự và bật/tắt theo `GW_FEATURES` (registry) |
| common | **`Clock`** | `now() -> datetime`, `monotonic()` | `system`, `fake` (test `exp`/`jti`/degraded/TTL) | — | — |
| common (agent, approval-signer, bff, gateway, mcp) | `TokenVerifier` | `verify(token, audience) -> Principal` (D16: ở `acme_common`; kiểm `iss`, `aud`, `exp`, `azp`, scope theo cấu hình từng service) | `oidc_jwks` (chuẩn OIDC) | — | — |
| docs-mcp | `DocumentRetriever` | `search(query, principal, k)` | `pgvector_hybrid` | qdrant, elasticsearch | Reranking(inner, `Reranker`) |
| docs-mcp | `Reranker` | `rerank(query, chunks)` | `none`, `bge_reranker` | viranker | — |
| docs-mcp | `DocumentLoader` | `load(path) -> Document` | `markdown`, `pdf`, `docx` (registry theo đuôi file) | html, confluence | — |
| tickets-mcp | `TicketRepository` | `get`, `list_for`, `search`, `read_for_intent`, `commit_write(intent, approval)` (UPDATE + `ticket_events` + `tool_audit` cùng transaction) | `postgres` | **jira**, zendesk, glpi | — |
| tickets-mcp | **`IntentIssuer`** | `issue(op, target, draft, ctx) -> IntentJws` (D14; `draft` = args đã chuẩn hoá + `before/after/expected_updated_at/risk_flags` do `TicketRepository.read_for_intent` tính; `ctx` = principal + taint/clock; adapter ký và lưu hash) | `es256_jws`, `permissive` (**chỉ `ACME_ENV=eval`**) | kms | — |
| approval-signer | **`IntentVerifier`** | `verify(intent_jws, principal) -> RenderModel` (principal từ token signer đã kiểm `aud`/`azp`, D13) | `es256_jws` | — | — |
| approval-signer | **`ApprovalSigner`** | `sign(intent, principal) -> approval_token` | `es256_jwt` | kms/hsm, step-up (WebAuthn/CIBA, sau v1.0) | — |
| tickets-mcp | **`ApprovalVerifier`** | `verify(token, principal, intent_record)` | `es256_jwt`, `permissive` (**chỉ `ACME_ENV=eval`**, ablation; WARNING mỗi lần dùng) | kms | — |
| tickets-mcp | `ReplayGuard` | `consume(jti, ttl) -> bool` | `redis`, `in_memory` | — | — |
| analytics-mcp | `AnalyticsRepository` | `sales_summary`, `top_customers`, `customer_lookup`, ... (*tuỳ chọn sau v1.0:* `run_readonly(safe_query)`) | `postgres` | clickhouse, bigquery | — |
| mcp (all) | `ToolServerHost` | `register(tool_spec, handler)`, `asgi_app()` | `mcp_sdk` **hoặc** `fastmcp` (chốt sau spike M0; phương án B: FastAPI tool server) | — | — |
| common (agent, bff) | `TokenBroker` (D16: ở `acme_common`, không còn ở `agent/ports`) | `token_for(user_token, audience, scopes)` | `oauth_token_exchange` (RFC 8693) | `static` (test), `client_credentials_with_user_token` (phương án B) | Caching(inner; khoá `(sub, aud, sorted scopes)`, TTL `exp-30s`, in-process) |
| agent | `ToolProvider` | `tools_for(agent_name, principal)` | `mcp_http` | — | — |
| bff | `AgentClient` (D15: class HTTP thường, một implementation, không phải port) | `run(...)`, `resume(...)`, `history(...)` | `http_sse` | — | — |
| bff | `SignerClient` (class HTTP thường, một implementation) | `verify_intent(...)`, `approve(...)` | — | — | — |
| bff | `TokenBroker` (dùng port của `acme_common`, cùng dòng trên) | `token_for(subject_token, audience, scopes)` | `oauth_token_exchange` | `static` (test) | Caching theo session |

**Đã bỏ khỏi bảng v1.1 (D11):** `UsageSink`, `AuditSink` (-> `EventSink`); `ToolAuditSink` (-> `EventSink`); `ToolRateLimiter` (dùng lại `RateLimiter`); `ChatModelFactory` (-> hàm thường `make_chat_model(role)` trong agent); `Chunker` (module thường `chunking.py`); `SqlValidator` (module thường, chỉ tồn tại khi bật raw SQL tuỳ chọn); `ToolInvoker` (class cụ thể bọc handler: schema -> scope -> rate limit -> timeout -> cắt output -> audit; không phải port). `ApprovalSigner` chuyển từ UI sang `approval-signer`. `Pseudonymizer` vẫn là service cụ thể dùng `PiiDetector`.

> Ví dụ cho thấy giá trị của thiết kế: muốn chuyển sang Jira thì chỉ cần thêm `adapters/jira.py` + `"jira": _load_jira` + block `tickets.jira.*` trong config. Toàn bộ quy tắc phân quyền, intent/approval và audit trong `TicketService` giữ nguyên.

### 9.3 Cấu trúc thư mục chuẩn cho mỗi package
Repo: `packages/bff` (Python, cùng layout bên dưới; image multi-stage) và `web/` (pnpm; Vite + React + TS strict). `packages/ui` không còn (Chainlit đã thay, D15).

**Quy tắc frontend (D15, clean-oop áp dụng cho TS):**
- Một `web/src/api/client.ts` duy nhất chứa `request()` (JSON, CSRF header, xử lý `session_expired`, zod validate) và `sse()` (`fetch-event-source`); **component không gọi `fetch`** hay SDK mạng.
- Interface `AgentStream`, `ApprovalApi`, `ThreadApi` trong `src/api/types.ts`; implementation HTTP một nơi; test dùng fake hoặc MSW. Type API sinh từ OpenAPI của BFF (`openapi-typescript`).
- Feature folder `features/{chat,approval,threads,admin}`; markdown qua `react-markdown` + `rehype-sanitize` (chặn ảnh/link ngoài trừ allowlist). Không lưu token ở JS/localStorage.
- CSP do BFF đặt: `default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'`. Cookie `__Host-sid` (dev http: `sid`), HttpOnly, Secure, SameSite=Strict; CSRF double-submit `X-CSRF-Token`.
- CI job `web`: `pnpm install --frozen-lockfile`, lint, typecheck, vitest, build; Playwright E2E trên compose.

Layout Python:
```
packages/<svc>/src/<svc>/
├─ ports/          # ABC + neutral types + errors (không import vendor)
├─ adapters/       # <vendor>.py: chỉ nơi này import SDK/HTTP của vendor
├─ decorators.py   # Retrying/Fallback/Metered/... (implement cùng port)
├─ factory.py      # registry dict + lazy loader, đọc Settings
├─ services/       # business logic, chỉ phụ thuộc ports
├─ api/            # FastAPI routes / MCP tool handlers, gọi services
└─ settings.py     # pydantic-settings, block config theo vendor
```

> **Đề xuất bị bác/hoãn v1.2.1:** (1) 03§15#1 / 05§14#1 (optional scope + refresh-token grant, signer từ chối `aud` chứa `agent-service`) -> **bác**, thay bằng token-exchange + kiểm `azp` (D13), vì đơn giản hơn và Keycloak ép được ở quyền exchange. (2) 05§14#2 `tickets.classification DEFAULT 0` + env `INTERNAL_FLOOR` -> **bác**, mặc định là 1 (`INTERNAL`) theo D14, không thêm env. (3) 01§21#2 tên method `append/read_all`, adapter `file_append` -> **đổi** thành `put/latest`, `file_append_only` (D14). (4) 05§14#5 mã `step_up_required` -> **hoãn** đến khi làm step-up (sau v1.0). (5) 01§21#6 khoá chỉ nằm trong `gateway.yaml`, 01§21#11 `embedding_model_rev` -> **hoãn**: thuộc 01/02/04, không phải hợp đồng liên service. (6) 02§12 C5 (taint là module thường, không có port `TaintStore`) -> **chấp nhận**, không đổi bảng port.

> `packages/common` (`acme_common`) chứa `TokenVerifier`, `Clock`, `audit/` (hash-chain HMAC dùng chung), `testing/` (các `Fake<Port>`). Module `common` chỉ dùng thuật ngữ trung lập "OIDC/JWKS"; tên `keycloak` chỉ ở `settings.py`/adapter. `packages/approval_signer` giữ nhỏ có chủ đích: chỉ phụ thuộc `fastapi`, `pyjwt`, `cryptography` và `acme_common`.
