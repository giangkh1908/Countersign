# Lộ trình triển khai theo milestone (v1.3)

> Dự án sản phẩm phát triển tự do, lộ trình theo **milestone** (không theo tuần cố định). Mỗi milestone kết thúc bằng một **bản chạy được** và test xanh, đạt **Definition of Done (DoD)** đo được. Ký hiệu agent: **R** = reader (Haiku), **W** = worker (Sonnet), **O** = orchestrator (quyết định + review).
> Phiên bản 1.3, 2026-10-29. Khớp `design/DECISIONS-v1.2.md` (D0–D15). D15: UI = React + TS + BFF ngay từ M1 (Chainlit đã thay, ADR-002).

## Cấu trúc repo (uv workspace)

```
AI_EXAMPLE/
├─ pyproject.toml            # uv workspace root
├─ docker-compose.yml
├─ models.lock               # model ML: repo, revision sha, sha256 từng file, license (D3)
├─ infra/                    # keycloak realm, postgres init (roles, RLS), redis ACL, prometheus, grafana
├─ web/                      # SPA Vite + React 18 + TS strict (pnpm); build vào image bff (D15)
├─ packages/
│  ├─ common/                # config, logging, JWT verify, Clock, audit hash-chain HMAC, schemas, testing/Fake*
│  ├─ gateway/               # FastAPI LLM gateway (egress mỏng, không model ML)
│  ├─ policy_sidecar/        # embed (bge-m3 ONNX), guard (Prompt Guard 2), NER (underthesea); core-only
│  ├─ approval_signer/       # giữ khoá ký approval, verify intent, render model (~300 dòng); core-only
│  ├─ mcp_docs/              # MCP RAG (+ taint)
│  ├─ mcp_tickets/           # MCP ticket (prepare_* / commit_intent, ký intent)
│  ├─ mcp_analytics/         # MCP DB read-only (tool tham số hoá)
│  ├─ agent/                 # LangGraph graph + service
│  ├─ bff/                   # FastAPI BFF :8300: phục vụ SPA + /auth + /api; giữ phiên + token (D15); không giữ khoá ký
│  └─ mock_provider/         # mock LLM có độ trễ/lỗi cấu hình được
├─ data/                     # generator dữ liệu ACME giả lập + corpus độc + tập test PII viết tay
├─ eval/                     # benchmark (k6/vegeta), promptfoo, security regression (pytest), notebook phân tích
└─ docs/                     # SOLUTION, ROADMAP, design/, adr/, research/, reviews/
```

## Tổng quan milestone

| Milestone | Chủ đề | Phụ thuộc |
|---|---|---|
| M0 | Spikes + phương án B | — |
| M1 v0.1 | Walking skeleton | M0 |
| M2 v0.2 | Gateway production-core | M1 |
| M3 v0.3 | Nghiệp vụ đầy đủ | M1, M2 (audit) |
| M4 v0.4 | Policy sidecar & tối ưu chi phí | M2, M3 |
| M5 v0.5 | Bộ đánh giá & red-team | M3, M4 |
| M6 v0.6 | Trang admin + polish UX/a11y/i18n (BFF + SPA có từ M1) | M3 (có thể song song M4–M5) |
| M7 v1.0 | Production hardening | M5, M6 |
| Tuỳ chọn | Sau v1.0 | M7 |

---

## M0 — Spikes (mỗi spike time-box 2 ngày, có phương án B)

Quy tắc: hết 2 ngày chưa đạt tiêu chí thì **chuyển sang phương án B** và ghi ADR; không kéo dài. (R21)

| Việc | Agent | Tiêu chí xong (đạt) | Phương án B nếu thất bại |
|---|---|---|---|
| **[XONG]** ([`research/05`](research/05-m0-verification.md)) Xác minh các mục "việc cần xác minh" ở SOLUTION §11 | R | Báo cáo có nguồn trong `docs/research/05-*.md` | — |
| Khung uv workspace, ruff, pytest, pre-commit, docker compose (postgres+pgvector, redis, keycloak) | W | `docker compose up` chạy; `uv run pytest` xanh | — |
| **[XONG]** Spike A ([`spikes/a_mcp_identity`](../spikes/a_mcp_identity/), [ADR-003](adr/ADR-003-mcp-host-auth.md)): MCP SDK stateless + identity: MCP server nhỏ kiểm JWT Keycloak, đọc claims trong tool | W | Tool trả `sub` và `department` của caller; sai audience bị 401 | **FastAPI tool server** tự viết (JSON-RPC tối giản) + middleware ASGI kiểm JWT; port `ToolServerHost` giữ nguyên |
| **[XONG]** Spike B ([`spikes/b_bff_token_exchange`](../spikes/b_bff_token_exchange/), [ADR-005](adr/ADR-005-token-flow.md); phương án B của token **không dùng**): BFF OIDC + exchange 2 audience (xác minh luật Keycloak exchange V2): BFF (client `chat-ui`) đăng nhập code + PKCE, exchange ra `aud=agent-service` và `aud=approval-signer`; LangGraph `interrupt()` + resume qua BFF | W | Token đăng nhập `aud=chat-ui` (không có `agent-service`/`approval-signer`); cả 2 exchange thành công; token `aud=agent-service` gọi signer bị 401/403; `agent-service` exchange tới signer bị Keycloak từ chối; một luồng approve/reject qua BFF | Cấu hình audience mapper/permission theo luật V2 khác (ghi ADR); nếu exchange không khả thi: BFF dùng client-credentials + header user token đã verify (giới hạn ghi rõ) |
| **[XONG]** Spike C ([`spikes/c_agent_downstream_exchange`](../spikes/c_agent_downstream_exchange/), [ADR-005](adr/ADR-005-token-flow.md); phương án B **không dùng**): Keycloak token exchange (RFC 8693) phía agent | W | Đổi token `aud=agent-service` lấy token `aud=tickets-mcp`, `aud=llm-gateway` | **client-credentials** + header `X-Acme-User-Token` đã verify; adapter `client_credentials_with_user_token` của `TokenBroker` |
| **[XONG]** Spike D ([`spikes/d_checkpoint_encryption`](../spikes/d_checkpoint_encryption/), [ADR-004](adr/ADR-004-checkpoint-encryption.md); phương án B không dùng): serializer mã hoá checkpoint LangGraph (`PostgresSaver`) | W | Checkpoint trong DB là ciphertext, resume sau `interrupt` đọc lại đúng | Mã hoá ở lớp lưu trữ (cột/ pgcrypto) + retention ngắn; ghi giới hạn |
| **[CÒN MỞ]** Pilot Prompt Guard 2 tiếng Việt: 50 mẫu độc + 50 mẫu lành | W + R (thu thập mẫu) | Báo cáo TPR/FPR; quyết định bật/tắt ở M4 | Giữ guard tắt; dùng heuristic + spotlighting; xem lại ở M4 |
| Chốt SDK MCP, UI, phương án token, serializer → ADR-001..004 | O | ADR được merge | — |

**DoD M0:** (D15) spike B xác minh được luật Keycloak V2 hoặc đã ghi phương án B; 4 spike + pilot có kết luận bằng văn bản (đạt hoặc chuyển B), mỗi cái ≤ 2 ngày; `docker compose up` chạy; ADR đã merge.

## M1 v0.1 — Walking skeleton

**Mục tiêu:** `docker compose up` chạy đầu-cuối: SPA React + BFF → agent (router + HITL) → gateway mỏng → docs-mcp + tickets-mcp, kể cả `close_ticket` qua luồng intent/approval.

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| `common`: config, log, `TokenVerifier` (`oidc_jwks`), `Clock`, kiểu/lỗi trung lập, `Fake*` | W | Test verify JWT đúng/sai `aud`, `exp` (dùng `FakeClock`) |
| `mock_provider` (OpenAI/Anthropic/Gemini, streaming, độ trễ/lỗi chỉnh được) | W | Dùng được cho test gateway |
| Gateway mỏng: auth key (HMAC+pepper), user token, 1 provider (Anthropic) + mock, `/v1/chat/completions` (stream + non-stream, tool calling), `usage_events` | W | Pass test bằng `openai` SDK và `ChatOpenAI` |
| docs-mcp: ingest (embed qua gateway `acme-embed`, có thể mock ở M1) + `search_documents` + ACL SQL/RLS + spotlighting | W | User phòng khác nhận 0 kết quả mật |
| tickets-mcp: tool đọc + `prepare_close_ticket` + `commit_intent`; khoá intent | W | Luồng intent → commit chạy; intent hết hạn/hash sai bị từ chối |
| `approval-signer`: `/v1/intents/verify`, `/v1/approvals` | W | Token sai `aud`/`sub` bị từ chối; không phụ thuộc Redis/DB |
| Agent: StateGraph (router + docs + ticket), token exchange (hoặc phương án B), `interrupt({intent_jws})` | W | 10 kịch bản mẫu chạy được |
| `bff` (FastAPI, `packages/bff`): OIDC code + PKCE (client `chat-ui`), cookie `__Host-sid` HttpOnly/SameSite=Strict, session `bff:sess:{sid}` (Redis ACL user `bff`), CSRF `X-CSRF-Token`, CSP, exchange `aud=agent-service` + `aud=approval-signer`, proxy SSE `/api/chat`, `/api/intents/verify`, `/api/approvals`, `/api/threads`, `/api/requests/{id}`; không giữ khoá ký | W | Test BFF với `FakeTokenBroker`/fake signer; token không có trong response tới trình duyệt |
| `web/` SPA tối thiểu (Vite + React + TS strict, TanStack Query, shadcn/ui): login, chat streaming (SSE qua POST), thẻ duyệt render từ render model (mọi `display_fields`, bidi escape), trích nguồn, chi phí; một `src/api/client.ts` (`request()`, `sse()`), component không gọi `fetch`; markdown `rehype-sanitize` | W | Demo đóng ticket có duyệt trên SPA; Vitest + MSW xanh |
| CI job `web` (pnpm frozen-lockfile, lint, typecheck, vitest, build) + Playwright E2E trên compose; image `bff` multi-stage | W | CI xanh |
| Seed tối thiểu (ACME: 2 phòng ban, ~30 tài liệu, ~100 ticket) | W | Seed lặp lại được |

**DoD M1:** (1) `docker compose up` rồi chạy kịch bản "đóng ticket" đầu-cuối thành công; (2) 5 kiểm thử bảo mật tối thiểu qua: sai `args` sau duyệt -> `intent_mismatch`, replay `jti` -> `approval_replayed`, intent hết hạn -> `intent_expired`, ticket đổi sau duyệt -> `conflict`, user khác phòng không đọc được tài liệu mật; **agent gọi `/v1/approvals` bằng chính token agent cầm (`aud=agent-service`, nhận được từ BFF) -> 401/403, token đăng nhập không có `aud ∋ {agent-service, approval-signer}`, và `agent-service` exchange tới `approval-signer` bị Keycloak từ chối (D13/D15, sửa N01/N02; không dùng token dựng riêng)**; (3) `uv run pytest` xanh, leak-grep rỗng; (4) README chạy từ máy sạch ≤ 15 phút; **(5) UI/BFF (D15):** (a) quét token: không có access/refresh/signer token hay khoá trong JS, localStorage, cookie (ngoài `sid` HttpOnly) hay response tới trình duyệt; (b) Playwright approve và reject xanh trên compose; (c) CSP chặn ảnh/script ngoài (ca exfil qua markdown `![](https://evil/...)` không phát sinh request); (d) thẻ duyệt hiển thị đủ `display_fields`, signer trả `intent_unrenderable` thì nút Duyệt bị khoá; (e) leak-grep `web/src` rỗng, job CI `web` xanh. M1 dài thêm ~1–1,5 tuần so với bản Chainlit.

## M2 v0.2 — Gateway production-core

**Mục tiêu:** gateway đủ dùng nội bộ.

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Rate limit RPM+TPM (Lua token bucket) + concurrency | W | Test đồng thời không vượt hạn mức |
| Usage + cost (`pricing.yaml`), budget key/phòng ban, reconcile 5 phút | W | Số liệu khớp `usage` của provider |
| Adapter Gemini; retry, timeout, circuit breaker, fallback theo alias | W | Chaos: provider A sập thì chuyển B |
| Thu hồi key qua pub/sub | W | Thu hồi < 1 s |
| Exact cache, `scope_hash` có `sub`; ẩn `x-acme-cache` với user thường | W | Canary: 0 hit chéo user/phòng ban |
| PII regex VN (CCCD, SĐT, STK, email, biển số, PERSON có stop-word) + pseudonymization | W | Recall ≥ 95% trên tập dev CCCD/SĐT/email |
| Degraded mode Redis (D5) | W | Test: tắt Redis, chi vượt ≤ ngưỡng đo được, 600 s -> 503 |
| Audit chain HMAC (`AUDIT_HMAC_KEY`) + anchor hằng giờ + script verify | W | Verify phát hiện được log bị sửa/xoá |
| Prometheus/Grafana (latency theo stage, cache, fallback, cost, degraded) | W | Dashboard chi phí theo phòng ban |
| Benchmark E1/E2 bản đầu (mock) | W | Có số baseline |

**DoD M2:** (1) overhead p95 < 30 ms ở 100 RPS khi chưa bật guard/NER (mock provider); (2) ≥ 99% request thành công khi một provider sập; (3) thu hồi key < 1 s; (4) 0 cache hit chéo user trong test canary; (5) verify audit phát hiện 100% bản ghi bị sửa trong test; (6) leak-grep rỗng, đặc biệt gateway không import `onnxruntime/torch/tokenizers`.

## M3 v0.3 — Nghiệp vụ đầy đủ

**Mục tiêu:** đủ luồng nghiệp vụ, an toàn dữ liệu nội bộ.

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| tickets-mcp: đủ `prepare_*`/`commit_intent` cho `create_ticket`, `add_comment`, `update_status`, `close_ticket`; audit ghi cùng transaction | W | Rollback đồng thời khi một bước lỗi; 0 thao tác ghi thiếu audit |
| analytics-mcp: **chỉ tool tham số hoá**, view `security_barrier` mask PII, RLS FORCE, thu hồi quyền cột PII, role read-only | W | `an_reader` không đọc được `core.*`; test SQL/GUC không có đường vào |
| Taint (D17): docs-mcp, analytics-mcp, `get_ticket` ghi `mcp:taint:{sub}:{thread_id}` + `:recent`; `acme.ticket_audience(draft)`; `prepare_*` gắn `possible_downgrade`; `TAINT_POLICY=warn\|block` | W | Test: đọc tài liệu mật rồi ghi ticket công khai -> cờ đỏ / bị chặn; taint còn hiệu lực qua ngày (khoá `recent`) và qua phòng ban |
| Máy trạng thái intent (00 §4.2), Redis lưu JWS + verify lại, `ticket_events.intent_id UNIQUE`, BFF `:rej` + giới hạn thẻ | W | Test máy trạng thái (xem DoD M3 mục 6) |
| Checkpoint mã hoá + retention 30 ngày + API xoá thread | W | Test: DB chỉ chứa ciphertext; job xoá hoạt động |
| Agent đủ 3 subgraph (docs, ticket, data) + input_guard; tập 150 câu có nhãn | W | Routing accuracy đo được |
| Dữ liệu ACME đầy đủ: 4 phòng ban, ~200 tài liệu, ~2.000 ticket, DB bán hàng | W | Seed lặp lại, seed cố định |
| Security regression v1 (E6) trong CI | W | Bảng vượt quyền = 0 |

**DoD M3:** (1) mọi tool ghi chạy qua intent/approval, 100% ghi có `tool_audit` cùng transaction, và ca "agent gọi `/v1/approvals` bằng chính token agent cầm -> 401/403" vẫn xanh với mọi MCP/audience mới (D13); (2) E6 = 0 truy cập trái phép trong ≥ 30 ca; (3) DB `agent` không chứa plaintext hội thoại; (4) routing accuracy ≥ 90% trên 150 câu; (5) `uv run pytest` xanh, leak-grep rỗng; (6) test máy trạng thái intent: 2 `commit_intent` song song cho cùng intent -> đúng 1 thành công, cái kia `approval_replayed`; crash giả lập ở `committing` -> sau 30s khôi phục đúng (`committed` nếu có `ticket_events.intent_id`, ngược lại `failed`); `expected_updated_at` lệch -> `failed` + `conflict`; (7) taint qua ngày (khoá `recent`, `thread_id` giả) và qua phòng ban ra `possible_downgrade` đúng.

## M4 v0.4 — Policy sidecar & tối ưu chi phí

**Mục tiêu:** tách model nặng khỏi gateway; giảm chi phí có kiểm soát.

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| `policy-sidecar`: `/v1/embed`, `/v1/guard`, `/v1/pii/ner`; verify `models.lock`; script convert/quantize chạy CI | W | Sidecar từ chối khởi động khi hash lệch; parity recall@k fp32 vs int8 (Δ ≤ 1 điểm) |
| Gateway gọi sidecar: timeout + fail-policy (`guard: fail_open\|fail_closed`, `ner: skip_on_error`) | W | Test sập sidecar: hành vi đúng chính sách |
| Chuyển ingest docs-mcp sang một runtime embedding duy nhất (qua `acme-embed`) | W | Cùng runtime cho ingest và query |
| Router `acme-auto` (`complexity_v1`) + provider prompt caching | W | Chạy được E3 |
| Semantic cache: chỉ populate từ nguồn tin cậy, per-scope | W | False-hit đo được; 0 rò chéo scope; mặc định tắt |
| Guard bật theo kết quả pilot M0/M4 | O + W | Có quyết định bật/tắt kèm TPR/FPR |
| NER underthesea, tập test PII ≥ 300 câu viết tay; so regex vs regex+CRF | W | CI theo entity (Wilson) |

**DoD M4:** (1) gateway image không chứa onnxruntime/torch/tokenizers; (2) E3 trên trace agent thật: giảm chi phí ≥ 50% tại iso-quality (chất lượng giảm ≤ 3 điểm %) so với baseline tất-cả-đắt, và vượt router ngẫu nhiên cùng tỉ lệ; (3) semantic cache: 0 rò chéo scope, false-hit < 1% (đo, bật mặc định tắt); (4) độ trễ có/không sidecar được báo cáo phân rã theo stage; (5) PII recall ≥ 95% (CCCD/SĐT/email), precision PERSON được báo cáo riêng; (6) ca sidecar quá tải/timeout/429: không đoạn tool/RAG chưa kiểm tra nào tới provider (bị thay bằng `[nội dung đã ẩn...]`), không tên người nào tới provider ngoài (`503 policy_unavailable`), embed ingest không làm đói guard/NER online; `gw_policy_skipped_total` tăng và alert kích hoạt.

## M5 v0.5 — Bộ đánh giá & red-team

**Mục tiêu:** đo và khoá chất lượng/bảo mật bằng CI.

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Benchmark E1 đầy đủ (từng tính năng, nhiều mức RPS, VM Linux cpuset), E2 chaos | W | Bảng + biểu đồ, phân rã theo stage |
| E3 chi phí/chất lượng: baseline tất-cả-rẻ, router ngẫu nhiên, router oracle; Pareto | W | Bảng + Pareto |
| **Security regression suite** trong CI: fault-injection (đổi args, replay `jti`, đổi ticket sau duyệt, intent giả, key sai, **agent gọi `/v1/approvals` bằng token của mình -> 403, agent exchange tới `approval-signer` bị từ chối**), cache chéo user, corpus RAG độc, ablation adapter `permissive` (profile `eval`) | W | CI fail khi hồi quy; 100% fault-injection bị từ chối |
| E4(1): tỉ lệ đề xuất độc hại tới thẻ duyệt + bị duyệt bởi approver mô phỏng | W | Bảng ASR/utility |
| E4(2): **user study 8–12 người**: thẻ args thô vs intent do server tính | O (thiết kế) + R (tổng hợp) | Tỉ lệ duyệt nhầm với khoảng tin cậy |
| E7/E8: Wilson CI theo nhóm, ≥ 2 model, 20% reject/edit; ≥ 100 mẫu gán nhãn bởi người, κ người–người/người–judge, `acme-judge` khác họ | W + R | Báo cáo kèm seed/prompt/phiên bản |
| promptfoo/garak quét; ánh xạ OWASP LLM 2025 + Agentic 2026 | R | Bảng ánh xạ |

**Ngân sách M5:** phòng EVAL trần cứng **160 USD** (dự kiến ~130 USD), key riêng `eval-regression` cho nightly regression (D14).

**DoD M5:** (1) security regression chạy trong CI mỗi PR, fail build khi hồi quy; (2) fault-injection 100% bị từ chối, ASR thao tác ghi = 0%; (3) có số liệu E1–E8 theo SLO của SOLUTION §9 (đạt hoặc có issue theo dõi cho mục chưa đạt); (4) user study hoàn tất với ≥ 8 người, báo cáo tỉ lệ duyệt nhầm kèm CI; (5) kết quả công bố seed/prompt/phiên bản; (6) security regression gồm các ca D17: commit song song/replay (`approval_replayed`), crash ở `committing`, taint qua ngày/qua phòng ban, intent đã từ chối bị trình lại, vượt 10 thẻ/thread/giờ, sidecar quá tải không lọt nội dung chưa kiểm.

## M6 v0.6 — Trang admin + polish UX/a11y/i18n

> BFF + SPA đã có từ M1 (D15, `docs/adr/ADR-002-ui-react-bff.md`, thay ADR-001/Chainlit). M6 mở rộng trên cùng codebase. Có thể chạy song song M4–M5 sau khi M3 xong.

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Trang admin (`features/admin`, BFF `/api/admin/*` yêu cầu role `admin`, proxy admin API gateway): quản lý key, budget, chi phí theo phòng ban, bật/tắt cache scope | W | Thay thao tác curl/Swagger; user không có role nhận 403 |
| Polish UX: sửa tham số (gọi lại `prepare_*`), diff trước/sau, `risk_flags` đỏ, lịch sử thread, trạng thái lỗi/tải | W | Review UX với ≥ 3 người dùng thử |
| a11y: điều hướng bàn phím, ARIA cho thẻ duyệt, tương phản; kiểm tra axe trong Playwright | W | 0 lỗi axe mức serious/critical |
| i18n (vi/en) cho toàn bộ chuỗi UI | W | Không còn chuỗi cứng trong component (lint) |
| Test BFF/SPA bổ sung cho `/api/admin/*` và các lỗi §6.4 (`session_expired`, `csrf_failed`) | W | Vitest + Playwright xanh |

**DoD M6:** (1) e2e "đóng ticket" + e2e admin chạy trên SPA; (2) quét token như DoD M1 (5a) vẫn xanh với trang admin; (3) CSP + sanitize qua security regression; (4) axe sạch lỗi serious/critical; (5) i18n vi/en đầy đủ.

## M7 v1.0 — Production hardening

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| TLS nội bộ (mTLS hoặc TLS + cert nội bộ), issuer/hostname thật | W | Không còn HTTP giữa service; test chứng chỉ sai bị từ chối |
| HA: ≥ 2 gateway, Redis Sentinel hoặc managed, Postgres backup + PITR | W | Diễn tập: tắt 1 gateway / failover Redis / restore PITR đạt RTO, RPO đề ra |
| Secret manager (Vault/SOPS), xoay khoá (pepper, HMAC audit, khoá intent/approval) | W | Xoay khoá không downtime |
| Audit anchor sang bucket object-lock | W | Verify audit từ anchor |
| Helm chart (tuỳ chọn) | W | `helm install` chạy được trên cluster thử |
| Runbook, SLO + alert (burn-rate), kiểm toán dependency (`uv.lock` hash, digest, `models.lock`) | W + O | Runbook diễn tập; alert bắn đúng trong chaos |
| Quét bảo mật cuối (SAST/dependency/container) | W | 0 lỗ hổng mức cao chưa xử lý |

**DoD M7:** (1) diễn tập sự cố đạt SLO đã ghi (availability, p95, thu hồi key); (2) không secret nào trong image/repo (quét tự động); (3) restore PITR thành công trong thời gian cam kết; (4) security regression + benchmark xanh trên bản release; (5) gắn tag v1.0 với changelog và runbook.

## Tuỳ chọn sau v1.0
| Hạng mục | Ghi chú |
|---|---|
| Raw SQL analytics (`run_readonly_sql`) + HMAC ctx (`app.sig`) + sqlglot allowlist | Thiết kế giữ ở `00-contracts` §3.4; bật bằng `ANALYTICS_ENABLE_RAW_SQL` |
| So sánh LiteLLM/Portkey (E9) | Pin digest, cùng mock |
| Langfuse (profile `obs`) | Chỉ metadata hoặc nội dung đã mask |
| Step-up WebAuthn/CIBA cho phê duyệt rủi ro cao | Giảm rủi ro UI backend bị chiếm; adapter `ApprovalSigner` |
| Jira adapter cho `TicketRepository` | Thêm `adapters/jira.py` + registry |

## Cách vận hành đội agent
1. Đầu mỗi milestone, **O** tách việc thành task có mục tiêu, file, tiêu chí xong và định dạng báo cáo.
2. Task độc lập chạy song song: các MCP server giao cho nhiều **W** cùng lúc, mỗi worker dùng một worktree riêng.
3. **R** làm research và đọc log/kết quả benchmark rồi tóm tắt lại.
4. **O** review diff, chạy test trước khi merge; quyết định mới thì ghi ADR.
