# ADR-005: Chuỗi token người dùng — Keycloak Standard Token Exchange V2, mỗi audience một request

- **Trạng thái:** Đã chấp nhận (2026-10-29), sau Spike B và Spike C (M0).
- **Người quyết định:** orchestrator; chủ dự án review
- **Bằng chứng:** `spikes/b_bff_token_exchange/{README.md,output.txt}` (ALL PASS), `spikes/c_agent_downstream_exchange/{README.md,output.txt}` (79/79 PASS); Keycloak 26.4.7
- **Liên quan:** D13, D15, D16, D17; contracts §3.4, §4, §9.2 (`TokenBroker`); 04 §4.2–4.3; 05 (luồng phê duyệt); 07 §8 (BFF); ADR-003

## Bối cảnh
D13/D15 yêu cầu token người dùng đi qua từng chặng với `aud` hẹp, và agent không bao giờ lấy được token cho `approval-signer`. Hai spike chạy thật trên realm `acme` cho thấy:

| Quan sát | Spike |
|---|---|
| Login code + PKCE (S256) qua `chat-ui` ra token chỉ `aud=chat-ui`; token không xuống trình duyệt | B |
| Exchange V2 giữ nguyên `sub`, `dept`, `clearance`, `sid`; **không có `act`/`may_act`**; không trả refresh token; TTL 300 s | B, C |
| `azp` sau exchange = **client gửi request** (`chat-ui` từ BFF, `agent-service` từ agent) | B, C |
| agent-service exchange sang `approval-signer` bị từ chối (400 `invalid_scope` / `Requested audience not available`) | B |
| Subject token có `aud` không chứa requester ⇒ 403 `Client is not within the token audience`; token hết hạn/bị sửa ⇒ 400 `Invalid token`; scope không gán ⇒ 400 `invalid_scope` (từ chối cả request) | C |
| **Một request có nhiều `audience` ⇒ Keycloak cấp token nhiều `aud`** (không chặn) | B, C |
| **Xin scope của đích khác vẫn lọt vào `scope`** (vd `aud=tickets-mcp` mang `llm:invoke`) | C |
| **`exp` của token đổi ra không bị chặn bởi `exp` của subject** (subject 15 s ⇒ token mới 300 s) | C |
| agent-service bật service account ⇒ tự lấy được `aud=tickets-mcp` (cả `tickets:write`) không gắn user, không có `dept` | C |
| Exchange vẫn chạy khi `serviceAccountsEnabled=false` | C (ca G) |
| Tên attribute client: `standard.token.exchange.enabled` (xác nhận bằng export) | B |
| Latency exchange (keep-alive) p50 10–12 ms, p95 18–21 ms; verify JWT ~0,1 ms | C |

Phương án B (client-credentials của agent + header `X-Acme-User-Token`) chạy được nhưng: buộc resource server nhận token `aud=agent-service` (token passthrough, đặc tả MCP cấm); một token user dùng được ở nhiều dịch vụ (replay chéo); agent cầm credentials + bất kỳ token user nào là dựng được danh tính đó; lệch contracts §3.4 và ADR-003.

## Quyết định
1. **Phương án chính: OAuth 2.0 Token Exchange (RFC 8693) qua Keycloak Standard Token Exchange V2.** Không dùng phương án B; giữ adapter `client_credentials_with_user_token` ở dạng ghi chú dự phòng, **không cài** trong M1.
2. **Mỗi request exchange đúng một `audience`** và chỉ các scope thuộc đích đó:
   - BFF: 2 request riêng — `aud=agent-service` + `agent:invoke`; `aud=approval-signer` + `signer:approve`.
   - Agent: mỗi đích một request — `docs-mcp`/`tickets-mcp`/`analytics-mcp`/`llm-gateway` với scope tương ứng.
3. **Hậu điều kiện bắt buộc trong adapter `TokenBroker`** (vì Keycloak không chặn): token trả về phải có `aud == [audience]` (đúng một phần tử) và `scope` (bỏ scope mặc định không phải quyền) ⊆ scope đã xin; sai ⇒ lỗi, không dùng token.
4. **`azp` thay cho `act`** để biết bên gọi. Resource server kiểm `azp` theo allowlist (`MCP_ALLOWED_AZP=agent-service`, gateway `agent-service`, signer `chat-ui`). Không dựa vào `act`.
5. **Chặn agent → signer bằng thiết kế scope:** không gán `signer:approve` (và mapper audience `approval-signer`) cho `agent-service`, kể cả tạm thời. Signer kiểm `aud=approval-signer`, `azp=chat-ui`, scope `signer:approve`, `sub == intent.sub`.
6. **`agent-service` tắt service account** (`serviceAccountsEnabled=false`) và đặt `access.token.lifespan=300`. Resource server **bắt buộc** có `sub`, `dept`, `clearance` trong token (thiếu ⇒ 401 `malformed`) — phòng thủ thêm nếu ai đó bật lại service account.
7. **Tác vụ nền không có người dùng** (job retention D17 gọi `forget` ở docs-mcp): **không** "thay mặt `sub`" (V2 không hỗ trợ impersonation). Dùng một client riêng `agent-maintenance` (confidential, chỉ client-credentials, `aud=docs-mcp`, scope duy nhất `docs:forget`); endpoint `/internal/taint/forget` nhận token đó, thao tác theo `thread_id`, ghi audit. Chi tiết làm khi tới việc retention.
8. **Port `TokenBroker`** (ở `acme_common`, D16):
   - `token_for(principal: Principal, user_token: str, audience: str, scopes: Sequence[str]) -> AccessToken` — `principal` là kết quả đã verify của token vào, dùng làm khoá cache; không giải mã lại.
   - Adapter `oauth_token_exchange` (tên theo chuẩn, không `keycloak_*`), fake `static` cho test.
   - Decorator `CachingTokenBroker`: khoá `(sub, sid, audience, sorted(scopes))`, TTL = `min(exp_mới, exp_subject) − 30 s` (không để token đổi ra sống lâu hơn token người dùng); `MeteredTokenBroker` đo latency/lỗi.
9. **Lỗi từ Keycloak là 400/403 tuỳ ca**, không phải 403 cố định: adapter dịch `invalid_scope`/`invalid_request`/`invalid_token`/`not within the token audience` sang lỗi miền (`TokenExchangeDenied`) và không lộ chi tiết cho người dùng.

## Hệ quả
- (+) Mỗi chặng chỉ có token `aud` hẹp, đúng D13/D15; resource server không cần biết agent; khớp ADR-003.
- (+) Chi phí nhỏ (~10–20 ms/exchange, cache hit ≈ 0).
- (−) Phải tự giữ hậu điều kiện (mục 3) và test hồi quy cho việc gộp audience / lọt scope — Keycloak không chặn.
- (−) Token đổi ra có thể sống lâu hơn session (tối đa 300 s); chấp nhận, kèm cache TTL theo `exp_subject`. Thu hồi tức thời cần introspection — chưa làm.
- (−) Thêm client `agent-maintenance` cho tác vụ nền.
- Việc kéo theo (sửa tài liệu/cấu hình):
  - `infra/keycloak/realm-acme.json`: agent-service `serviceAccountsEnabled=false`, `access.token.lifespan=300` (**đã sửa** cùng ADR này).
  - contracts §4 / §3.4 / dòng 373 (bỏ "service account"), §398 (bỏ `act`), §9.2 (chữ ký `token_for`, cache key, hậu điều kiện).
  - 04 §4.2–4.3: dòng 1072/1122 (service account), 1143 (bỏ feature flag thừa), Keycloak 26.8.1 (CVE).
  - 05 dòng ~499: mã lỗi 400 thay vì 403.
  - 03 §948: job retention dùng `agent-maintenance` thay vì "service account thay mặt sub".
  - M1: signer kiểm `scope`; agent chống replay `jti` của intent JWS; Playwright cần mục hosts cho `keycloak.acme.local`.
