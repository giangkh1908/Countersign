# Quyết định v1.2 (sau review-01-opus) — nguồn chung cho mọi worker

> Ngày 2026-10-28. Orchestrator quyết định sau khi đọc `docs/reviews/review-01-opus.md` và ý kiến chủ dự án.
> Mọi file 00–05, SOLUTION, ROADMAP phải khớp file này. Mâu thuẫn → file này thắng.

## D0. Định khung dự án (THAY ĐỔI LỚN)
- **Không phải đồ án/luận văn.** Đây là **dự án sản phẩm phát triển tự do**: nền tảng trợ lý AI nội bộ self-host, hướng tới chạy được thật trong doanh nghiệp.
- Bỏ mọi ngôn ngữ "đồ án / luận văn / hội đồng / sinh viên / giảng viên / 14 tuần / đóng góp khoa học". Thay bằng: mục tiêu sản phẩm, milestone phát hành, tiêu chí chấp nhận (acceptance), SLO.
- Lộ trình theo **milestone** (không theo tuần cố định), mỗi milestone có Definition of Done:
  - **M0 Spikes** (time-box mỗi spike 2 ngày, có phương án B ghi sẵn — R21).
  - **M1 v0.1 Walking skeleton**: Chainlit → agent (router + HITL) → gateway mỏng (auth key + user token + 1 provider + mock + usage) → docs-mcp (search + ACL) + tickets-mcp (đọc + `close_ticket` qua luồng intent/approval D1). Chạy `docker compose up` đầu-cuối.
  - **M2 v0.2 Gateway production-core**: rate limit, budget, 2 provider + fallback/breaker, exact cache, PII regex VN, audit chain (D6), Prometheus/Grafana.
  - **M3 v0.3 Nghiệp vụ đầy đủ**: tickets-mcp đủ tool ghi qua intent; analytics-mcp **chỉ tool tham số hoá** (D9); checkpoint mã hoá + retention (D7); taint (D8).
  - **M4 v0.4 Policy sidecar & tối ưu chi phí**: policy-sidecar (D2) gồm embed/guard/NER; router `acme-auto`; semantic cache có kiểm soát (D4); pilot guard tiếng Việt (R17) trước khi bật.
  - **M5 v0.5 Bộ đánh giá & red-team**: benchmark + security regression suite chạy CI; user study approval (D10).
  - **M6 v0.6 UI React + TS + BFF + trang admin** (ADR-001).
  - **M7 v1.0 Production hardening**: TLS nội bộ (mTLS hoặc TLS + cert nội bộ), HA (≥2 gateway, Redis Sentinel hoặc managed, Postgres backup/PITR), secret manager (Vault/SOPS), Helm chart tuỳ chọn, runbook, SLO + alert.
  - **Tuỳ chọn sau v1.0**: raw SQL analytics (L2–L5 + HMAC ctx), so sánh LiteLLM/Portkey (E9), Langfuse, step-up/CIBA/WebAuthn cho phê duyệt, Jira adapter.

## D1. Phê duyệt ràng buộc giao dịch (R01, R05) — THIẾT KẾ LẠI
Giả định đe doạ: **agent có thể bị chiếm/bị lừa hoàn toàn**. Nguyên tắc "What You See Is What You Sign": người dùng chỉ thấy dữ liệu do **server tính và ký**, chữ ký gắn với đúng dữ liệu đó.

Thành phần mới: **`approval-signer`** — service nhỏ riêng (≤ ~300 dòng, FastAPI + PyJWT/cryptography, không dependency nặng), mạng `core` only, không egress, cổng **8310**. Giữ khoá riêng ES256 ký approval. Chainlit KHÔNG còn giữ khoá.

Luồng (thay cho luồng cũ ký `args`):
1. Agent muốn ghi → gọi tool **`prepare_<op>(args)`** trên tickets-mcp (vd `prepare_close_ticket`). Cần scope `tickets:write`, **không** thay đổi dữ liệu. tickets-mcp tự đọc DB, tính **intent**:
   `{intent_id, op, target:{ticket_code}, before:{...}, after:{...}, expected_updated_at, args_canonical, sub, risk_flags[], iat, exp=iat+300}`
   ký JWS ES256 bằng **khoá intent của tickets-mcp**; lưu `mcp:tickets:intent:{intent_id}` (HASH `{sha256, sub, status}`, TTL 300s) vào redis-state.
2. Agent `interrupt({intent_jws})`. Agent **không** dựng preview; mọi trường hiển thị lấy từ intent.
3. UI backend gửi `intent_jws` tới `approval-signer POST /v1/intents/verify` → signer xác minh chữ ký MCP (public key mount sẵn), `exp`, trả **render model** (before/after/risk_flags). UI chỉ render từ render model này.
4. User bấm Duyệt → UI backend gọi `POST /v1/approvals {intent_jws}` kèm **access token của user** (aud gồm `approval-signer`). Signer: verify user token (JWKS, iss, aud, exp), kiểm `sub == intent.sub`, intent chưa hết hạn → ký **approval token**:
   `{iss:"acme-approval", aud:"tickets-mcp", sub, intent_id, intent_sha256, jti, iat, exp=iat+120}`.
5. UI resume graph `Command(resume={decision:"approve", approval_token})`. Agent gọi **`commit_intent(intent_id, approval_token)`**. tickets-mcp kiểm: chữ ký approval, aud, `sub == caller.sub`, intent tồn tại + `sha256` khớp + status `pending`, `jti` SET NX (`mcp:tickets:jti:{jti}`), rồi thực thi với `expected_updated_at` (TOCTOU → `conflict`), ghi `ticket_events` + `tool_audit` **trong cùng transaction** (D6), đặt intent `status=committed`.
6. **Sửa (edit)**: UI gửi args mới cho agent → agent gọi lại `prepare_*` → intent mới (không bao giờ ký args do UI/agent tự dựng).
7. Tool ghi trực tiếp cũ (`create_ticket`, `close_ticket`... nhận approval_token theo args) **bị bỏ**; tool ghi = cặp `prepare_<op>` + `commit_intent`.
- Mã lỗi thêm: `intent_not_found`, `intent_expired`, `intent_mismatch`, (giữ `approval_*`, `conflict`).
- Rủi ro còn lại (ghi rõ): UI backend bị chiếm có thể xin chữ ký cho intent của chính user đang đăng nhập → giảm thiểu ở M6 (BFF tối giản) và tuỳ chọn step-up (WebAuthn/CIBA) cho thao tác rủi ro cao.
- Port mới: `IntentIssuer` (tickets-mcp), `IntentVerifier` + `ApprovalSigner` (approval-signer), `ApprovalVerifier` (tickets-mcp). Adapter permissive cho ablation chỉ khi `ACME_ENV=eval`.

## D2. Tách gateway: egress mỏng + policy sidecar (R06, R14)
- **`gateway`** (giữ khoá provider, egress duy nhất): auth, ratelimit, budget, PII **regex** (thuần Python), cache exact, route, provider adapters, audit, metrics. **Không** nạp onnxruntime/torch/tokenizers/HF model.
- **`policy-sidecar`** (mới, cổng **8010**, `core` only, không khoá, không egress): `/v1/embed` (bge-m3 ONNX), `/v1/guard` (Prompt Guard 2), `/v1/pii/ner` (underthesea CRF). Gateway gọi qua HTTP nội bộ với timeout + fail-policy cấu hình (`guard: fail_open|fail_closed`, `ner: skip_on_error`).
- **Một runtime embedding duy nhất** cho ingest và query: ingest của docs-mcp gọi `policy-sidecar /v1/embed` (hoặc qua gateway alias `acme-embed` → sidecar). Parity test = so recall@k fp32 vs int8 trên tập dev (Δ ≤ 1 điểm), không so cosine từng vector.

## D3. Supply chain cho model (R07)
`models.lock` (repo, revision commit sha, file + sha256, license). Tải bằng `huggingface_hub` với `revision` cố định, `trust_remote_code=False`, chỉ `*.safetensors`/`*.onnx`; script convert/quantize trong repo, chạy CI, xuất hash; sidecar verify hash khi khởi động. Ghi license: Prompt Guard 2 (Llama license), bge-m3 (MIT), underthesea (kiểm tra GPL).

## D4. Cache (R08, R09)
- Mặc định (M2): **exact cache**, scope_hash **có `sub`** (per-user) — đổi sang per-scope chỉ khi admin bật cho alias/system prompt "public FAQ".
- Semantic cache (M4, tuỳ chọn bật): chỉ **populate từ nguồn tin cậy** (FAQ đã duyệt / admin warm-up), không populate từ response người dùng thường; per-scope.
- Header `x-acme-cache` và `x_acme.cache` **chỉ trả cho key admin/EVAL**; user thường không thấy.
- Đo hit-rate và tiết kiệm **trên trace agent thật** (replay), không chỉ RAG cố định. Ưu tiên tiết kiệm qua router + **provider prompt caching**.

## D5. Degraded mode Redis (R20)
Hạn mức in-memory = limit / (N_worker × N_instance) (đọc từ config); trong degraded chỉ phục vụ alias rẻ (`acme-fast`); TTL cache key L1 rút ≤ 30s để thu hồi vẫn có hiệu lực; metric `gw_degraded_overspend_max_usd`. Hết 600s → 503 `service_unavailable`.

## D6. Audit (R15)
Hash chain dùng **HMAC-SHA256 với khoá ngoài DB** (`AUDIT_HMAC_KEY` secret); anchor mỗi giờ ký + ghi ra kho append-only ngoài DB (dev: thư mục mount riêng chỉ-append + commit git repo `audit-anchors`; prod: bucket object-lock). Audit hành động ghi của tickets-mcp ghi **đồng bộ, cùng transaction** với UPDATE. Ghi rõ giới hạn "không chống DBA có khoá HMAC".

## D7. PII nội bộ (R12)
Checkpoint LangGraph **mã hoá mặc định** (serializer mã hoá — xác minh API trong spike), retention thread 30 ngày (job xoá) + API xoá thread; Langfuse (nếu bật) chỉ metadata hoặc đã mask qua `policy-sidecar`/gateway PII; log không chứa nội dung.

## D8. Taint chống confused-deputy theo clearance (R16)
docs-mcp ghi `mcp:taint:{sub}` = max classification đã trả cho user (TTL 30 phút, phía server — agent không giả được). `prepare_*` của tickets-mcp so với visibility của ticket đích: nếu ghi dữ liệu có thể đến người có clearance thấp hơn → thêm `risk_flags:["possible_downgrade"]` vào intent, UI cảnh báo đỏ; chính sách cấu hình `warn|block`.

## D9. Analytics (R19)
MVP: **chỉ tool tham số hoá** + view `security_barrier` đã mask + RLS FORCE + role read-only; thu hồi mọi quyền cột PII trên bảng gốc. `run_readonly_sql` + HMAC ctx (`app.sig`) chuyển sang **tuỳ chọn sau v1.0**, giữ thiết kế trong tài liệu ở mục "Tuỳ chọn".

## D10. Đánh giá = benchmark + security regression + user study (R03, R10, R11, R13, R17, R22, R23)
- Đổi tên: "Bộ đánh giá" gồm (a) **benchmark hiệu năng/chi phí**, (b) **security regression suite** (chạy CI, fail build khi hồi quy), (c) **user study** phê duyệt.
- E4 tách: (1) tỉ lệ đề xuất độc hại tới được thẻ duyệt + tỉ lệ bị duyệt bởi approver mô phỏng "ngây thơ"; (2) **user study 8–12 người**: tỉ lệ duyệt nhầm khi thẻ hiển thị args thô vs intent do server tính; (3) **fault-injection** (agent độc: đổi args, replay jti, đổi ticket sau duyệt, intent giả, ký key sai) → đếm số lần MCP từ chối — trình bày là kiểm thử thuộc tính bảo mật.
- E3: thêm baseline tất-cả-rẻ, router ngẫu nhiên cùng tỉ lệ, router oracle; chỉ số chính chi phí tại iso-quality + Pareto; đo trên trace agent.
- Dữ liệu: ≥100 mẫu gán nhãn bởi người (κ người–người, người–judge); judge khác họ (`acme-judge` Gemini trước); báo cáo riêng trên phần viết tay; công bố seed/prompt/phiên bản.
- E7: tập test chính ≥300 câu viết tay (không dấu, viết tắt, số tách) — tập sinh chỉ làm dev; so regex vs regex+CRF; CI theo entity (Wilson).
- E1: báo cáo phân rã độ trễ theo stage, ghi rõ cấu hình có/không gọi sidecar; chạy VM Linux cpuset.
- E8: Wilson CI theo nhóm, ≥2 model, 20% quyết định reject/edit.
- Guard pilot (R17) là điều kiện để bật guard ở M4.
- Mục tiêu số (p95, %...) chuyển thành **SLO/acceptance của sản phẩm**, không phải "giả thuyết nghiên cứu".

## D11. Ports cân bằng (R18) — sửa contracts §9.2
- **Giữ** (biên vendor/hạ tầng thay được hoặc cần fake): `ChatProvider`, `Embedder`, `PiiDetector`, `InjectionGuard`, `ResponseCache`, `ModelRouter`, `RateLimiter`, `SpendTracker`, `CircuitBreaker` (redis + in_memory degraded), `KeyStore`, `TokenVerifier`, `TokenBroker`, `ToolProvider`, `DocumentRetriever`, `Reranker`, `DocumentLoader` (nhiều định dạng), `TicketRepository`, `AnalyticsRepository`, `ToolServerHost`, `ReplayGuard`, `AgentClient` (dùng lại ở BFF M6), `PipelineStage`.
- **Mới**: `Clock` (test exp/jti/degraded/TTL), `IntentIssuer`, `IntentVerifier`, `ApprovalSigner`, `ApprovalVerifier`.
- **Gộp**: `UsageSink` + `AuditSink` → `EventSink` (append usage/audit records; adapter postgres).
- **Bỏ port → module thường**: `ChatModelFactory` (hàm `make_chat_model(role)`), `Chunker`, `SqlValidator`.

## D12. Khác
- 2 Redis instance **giữ nguyên** (orchestrator không theo đề xuất gộp: chính sách eviction trái ngược, chi phí thêm 1 container không đáng kể).
- Bỏ mọi nhắc Presidio trong vai trò thành phần chính (R24); Presidio chỉ là baseline ngoài tuỳ chọn.
- R26: regex PERSON thêm stop-word sau danh xưng, ≥2 âm tiết viết hoa, đo precision riêng.
- R25: động cơ "vì sao tự xây gateway" dựa trên **yêu cầu kiến trúc** (uỷ quyền theo user, PII VN, audit, bề mặt tấn công nhỏ); sự cố LiteLLM chỉ trích dẫn phần có advisory chính thức (GHSA/OSV/Microsoft blog), phần còn lại ghi "theo báo cáo của…, chưa xác minh".
- R27: giữ advisory lock, ghi hướng mở rộng.
- Service mới cập nhật vào contracts §1: `policy-sidecar` 8010, `approval-signer` 8310 (đều `core` only). Env, Redis ACL user (`signer` không cần Redis; `docs` thêm `~mcp:taint:*` write, `tickets` thêm `~mcp:taint:*` read + `~mcp:tickets:intent:*`), Keycloak client `approval-signer` (bearer-only audience) cập nhật tương ứng.

## D13. Tách token cho approval-signer (bổ sung sau vòng sửa v1.2; phát hiện bởi W3)
Vấn đề: nếu access token user mang cả `aud=agent-service` và `aud=approval-signer` thì agent (giả định có thể bị chiếm) cầm token đó tự gọi `/v1/approvals` → phá luồng D1.
Quyết định:
- **Bỏ** audience mapper `approval-signer` trên token đăng nhập của `chat-ui`. Token UI chuyển cho agent chỉ có `aud=agent-service`.
- UI backend (Chainlit nay, BFF ở M6) tự **token exchange (RFC 8693)** `subject_token=<token user>` → `audience=approval-signer`, giữ token này **chỉ trong server-side session** (khoá theo `session_id`), không bao giờ gửi cho agent hay trình duyệt; TTL ngắn (≤5 phút), không cache sang session khác.
- Keycloak: quyền token-exchange tới audience `approval-signer` **chỉ cấp cho client `chat-ui`** (và `bff` ở M6). Client `agent-service` chỉ được exchange tới `llm-gateway`, `docs-mcp`, `tickets-mcp`, `analytics-mcp`.
- approval-signer kiểm: `aud` chứa `approval-signer` **và** `azp ∈ {chat-ui, bff}` **và** `sub == intent.sub`; ngược lại `403 forbidden`.
- Thêm ca security regression: "agent dùng token của mình gọi `/v1/approvals`" → 401/403; "agent thử exchange tới approval-signer" → Keycloak từ chối.

## D14. Gộp phụ thuộc contracts từ vòng v1.2 (orchestrator chốt)
- Port lưu anchor audit: tên thống nhất **`AnchorStore`** (`put(anchor)`, `latest()`), adapter `file_append_only`, `s3_object_lock` (sau). Không dùng tên `AuditAnchorSink`.
- `EventSink` thêm `flush()`; ghi audit đồng bộ khi cần qua `append(record, sync=True)` (không thêm method riêng `append_sync`).
- `IntentIssuer.issue(op, target, draft, ctx)`: chấp nhận tham số `draft` (args đã chuẩn hoá) như 02 đề xuất.
- Redis TTL `mcp:tickets:intent:*` = intent `exp` + 30s (330s mặc định). Xoay khoá ES256 (intent, approval) overlap 15 phút, JWKS công bố cả `kid` cũ và mới trong thời gian overlap.
- Ngân sách EVAL: dự kiến ~130 USD, **trần cứng 160 USD**; thêm key `eval-regression` (dept EVAL) cho nightly regression.
- Env mới: `MODELS_LOCK_SHA256`, `SIDECAR_TOKEN_PREV` (xoay token sidecar), nhóm `*_TLS_CERT|_KEY|_CA` (chỉ bật ở M7).
- Cột: `tickets.classification` (mặc định `INTERNAL`), `tool_audit.intent_id` (nullable), `ticket_events.intent_id`; role `mcp_audit_w` giữ INSERT-only.
- `models.yaml`: `acme-embed` trỏ `sidecar/embed` (thay `local/bge-m3`).
- Admin cache endpoint của gateway (01) đưa vào contracts §5 / API admin.

## D15. UI = React + TypeScript + BFF ngay từ MVP (thay Chainlit; ADR-002 thay ADR-001)
Người dùng quyết định bỏ Chainlit. Đồng thời sửa N01/N02 (review-02) vì BFF là nơi giữ và đổi token.
**Thành phần**
- Service `bff` (FastAPI, `packages/bff`, cổng **8300**, mạng `edge`+`core`) thay service `ui`. BFF phục vụ SPA đã build (cùng origin, không CORS) + `/auth/*` + `/api/*`. Dev: Vite 5173 proxy → 8300.
- Frontend `web/` (pnpm): Vite + React 18 + TypeScript strict, React Router, TanStack Query, Tailwind + shadcn/ui, `react-markdown` + `rehype-sanitize` (chặn ảnh/link ngoài trừ allowlist), `@microsoft/fetch-event-source` (SSE qua POST), `zod` validate runtime, type sinh từ OpenAPI của BFF (`openapi-typescript`), Vitest + Testing Library + MSW, Playwright E2E, ESLint (typescript-eslint) + Prettier. Phiên bản chính xác pin trong lockfile, xác minh ở M0.
**Quy tắc frontend (clean-oop)**: một `src/api/client.ts` duy nhất (`request()`, `sse()`); component không gọi `fetch`; interface `AgentStream`, `ApprovalApi`, `ThreadApi` trong `src/api/types.ts`, test dùng fake/MSW; feature folder `features/{chat,approval,threads,admin}`.
**Thẻ duyệt (sửa N03)**: chỉ render từ render model do signer trả (`/api/intents/verify`); signer trả `display_fields` phủ **toàn bộ** `args_canonical` + `before/after`; signer từ chối (`422 intent_unrenderable`) nếu có trường không hiển thị được; UI render mọi field theo kiểu, kiểu lạ → không cho bấm Duyệt; hiển thị ký tự bidi/điều khiển dạng escape.
**BFF**
- OIDC Authorization Code + PKCE, client `chat-ui` (confidential, giữ tên). Cookie phiên `__Host-sid` (HttpOnly, Secure, SameSite=Strict; dev http dùng `sid`). Phiên ở `redis-state` key `bff:sess:{sid}` (idle 30 phút, tuyệt đối 8 giờ); refresh token mã hoá AES-GCM bằng `BFF_SESSION_KEY`. CSRF: SameSite=Strict + header `X-CSRF-Token` (double-submit) cho mọi request đổi trạng thái. CSP: `default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`.
- Endpoint: `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`, `GET /api/me`, `POST /api/chat` (SSE proxy tới agent), `GET /api/threads`, `DELETE /api/threads/{id}`, `POST /api/intents/verify`, `POST /api/approvals` (BFF gọi signer rồi resume agent với approval token), `GET /api/requests/{id}` (chi phí). M6: `/api/admin/*` (realm role `admin`, proxy admin API gateway).
- Code: `AgentClient`, `SignerClient` là class HTTP thường (một implementation, D11); đổi token dùng lại port `TokenBroker` (adapter `oauth_token_exchange`); Redis dùng trực tiếp (hạ tầng cố định).
**Luồng token (thay phần Keycloak của D13, sửa N01/N02)**
- Token đăng nhập: `aud=chat-ui` (audience mapper trên chính client), **không** gửi cho agent.
- BFF token-exchange: (a) → `aud=agent-service`, gửi cho agent mỗi request; (b) → `aud=approval-signer`, chỉ ở server-side session, không rời BFF. Đáp ứng luật Keycloak exchange V2 (client gọi exchange phải nằm trong `aud` của subject token) — xác minh ở spike C.
- `agent-service` exchange token `aud=agent-service` của nó → `llm-gateway` + 3 MCP; **không** tới `approval-signer`.
- Bỏ client `bff` riêng (BFF dùng client `chat-ui`); signer kiểm `aud ∋ approval-signer`, `azp == chat-ui`, `sub == intent.sub`.
- Test D13/F22 phải dùng **chính token agent cầm** (`aud=agent-service`) gọi signer → 401/403, và agent-service exchange tới signer → Keycloak từ chối.
**Hạ tầng/CI**: Redis ACL user `bff` `~bff:sess:*` trên redis-state; env `BFF_PUBLIC_URL`, `BFF_SESSION_KEY`, `BFF_OIDC_CLIENT_SECRET`, `BFF_AGENT_URL`, `BFF_SIGNER_URL`; CI job `web` (pnpm install --frozen-lockfile, lint, typecheck, vitest, build) + Playwright E2E chạy trên compose; image `bff` build multi-stage (node build SPA → python runtime).
**Roadmap**: M1 gồm BFF + SPA tối thiểu (login, chat streaming, thẻ duyệt, trích nguồn, chi phí) — M1 dài thêm ~1–1,5 tuần. M6 đổi thành: trang admin (key, budget, chi phí theo phòng ban), polish UX, a11y, i18n. Spike Chainlit OIDC trong M0 bị bỏ, thay bằng spike "BFF OIDC + exchange 2 audience".

## D16. Đồng bộ sau vòng D15 (orchestrator chốt)
- Role quản trị: realm role **`admin`** (không dùng `acme-admin`).
- Client scope: `agent:invoke` (BFF → agent, có trong token exchange `aud=agent-service`), `signer:approve` (BFF → signer). Agent/signer kiểm scope ngoài `aud`/`azp`.
- `display_fields[].kind`: nguồn chuẩn là `05-approval-flow.md` (§ render model); 07 và 00 dùng đúng tập đó.
- Chấp nhận các quyết định trong 07: BFF giữ `intent_jws` trong `bff:sess:{sid}:pend` (trình duyệt chỉ gửi `thread_id`/`interrupt_id`); approve phải kèm `intent_sha256` đã verify; `POST /api/resume`, `GET /api/threads/{id}/messages`; cookie `__Host-login` SameSite=Lax chỉ cho callback; bidi/control khoá nút Duyệt, zero-width chỉ cảnh báo; CSP thêm `object-src 'none'`; `TokenBroker`/`TokenVerifier` chuyển vào `acme_common`; Redis user `bff` chỉ lệnh đơn, không `MULTI/EVAL`.
