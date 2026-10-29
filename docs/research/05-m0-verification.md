# 05 — Xác minh M0: SOLUTION §11 và các mục [cần xác minh]

> Reader (Haiku) nghiên cứu, orchestrator review và đối chiếu với kết quả chạy thật, 2026-10-29.
> Thang tin cậy: **Cao** = mã nguồn hoặc tài liệu/advisory chính thức; **TB** = nguồn chính thức thiếu chi tiết hoặc nhiều nguồn thứ cấp khớp nhau; **Thấp** = suy luận hoặc chỉ một nguồn.
> **Kết quả chạy thật thắng nguồn đọc được.** Chỗ nào hai bên mâu thuẫn được đánh dấu ⚠.

## Tóm tắt

| # | Mục | Kết luận | Tin cậy |
|---|---|---|---|
| 1 | `mcp` / `fastmcp` | `mcp` 2.3.0 và `fastmcp` 4.1.4 là bản mới nhất. `fastmcp` có sẵn `JWTVerifier`, `get_access_token()`, `stateless_http`. `mcp` 2.3 không có JWT verifier sẵn (phải tự viết `TokenVerifier`); `FastMCP` đã đổi tên thành `MCPServer` | Cao |
| 2 | OWASP Agentic | Tên ASI01–ASI10 lấy từ nguồn thứ cấp; trang chính thức trả 404 | TB |
| 3 | Keycloak token exchange V2 | Được hỗ trợ chính thức từ 26.2 và bật mặc định (`token-exchange-standard:v2`). Bản hiện hành 26.8.1 vá CVE-2026-97846. Không phát `act`. Không có "allowed audiences" riêng: kiểm soát qua client scope và audience mapper | Cao (luật) / Thấp (tên attribute) |
| 4 | Advisory LiteLLM | CVE-2026-42208 = GHSA-r75f-5x8p-qvmc. Sự cố 03/2026 = GHSA-5mg7-485q-xm76 / MAL-2026-2144. Sự cố 21/10/2026 = v1.107.0. **Không tìm thấy nguồn Microsoft 23/10** | Cao |
| 5 | Exchange 2 audience từ `chat-ui` | Làm được bằng **hai request riêng** (mỗi request một `audience` + `scope`). Chặn `agent-service` bằng thiết kế scope. Cần spike B để kiểm | TB |
| 6 | Serializer mã hoá checkpoint | `EncryptedSerializer.from_pycryptodome_aes()` (đọc `LANGGRAPH_AES_KEY`). **Không mã hoá mặc định**. Cột `checkpoint` và `metadata` vẫn là plaintext | Cao |
| 7 | License | Prompt Guard 2: Llama 4 Community License (gated). bge-m3: MIT. underthesea: **Apache-2.0** (không phải GPL) | Cao |
| 8 | Redis 8 | `rename-command` vẫn được hỗ trợ. ⚠ Docs redis.io nói có `@search`, nhưng **image `redis:8` (8.10.3) chạy thật không có Query Engine và không có `@search`** (xem §8) | Cao (chạy thật) |

---

## 1. Python `mcp` và `fastmcp`

**Kết luận.** `mcp` 2.3.0 (MIT, 2026-10-02) và `fastmcp` 4.1.4 (Apache-2.0, 2026-10-26; 4.2.0a1 là pre-release). Trong `mcp` 2.x, `FastMCP` đổi tên thành `mcp.server.mcpserver.MCPServer`.

**`mcp` 2.3.0** (đọc mã nguồn wheel):
- `MCPServer(..., token_verifier=..., auth=AuthSettings(issuer_url=..., resource_server_url=..., validate_token_resource=True))`.
- Giao thức `mcp.server.auth.provider.TokenVerifier`: `async def verify_token(token) -> AccessToken | None`. `AccessToken` có `token, client_id, scopes, expires_at, resource, subject, claims`.
- `validate_token_resource=True`: từ chối token có `resource` (`aud`) khác `resource_server_url`.
- Đọc danh tính trong tool: `mcp.server.auth.middleware.auth_context.get_access_token()`, dùng `.claims["sub"]`… (lấy từ contextvar; **chưa chạy thử** trong handler).
- Stateless: `streamable_http_app(stateless_http=True)`; `json_response=True` trả JSON thay vì SSE.

**`fastmcp` 4.1.4:**
- `FastMCP(name, auth=JWTVerifier(jwks_uri=..., issuer=..., audience=..., algorithm="RS256"|"ES256", required_scopes=...))`.
- Trong tool: `fastmcp.server.dependencies.get_access_token()` có `.claims`, `.subject`, `.scopes`, `.client_id`.
- Stateless: `run(transport="http", stateless_http=True)` hoặc env `FASTMCP_STATELESS_HTTP`.
- Phụ thuộc `fastmcp-slim` và `mcp>=2.3.0,<3`.

**Nguồn:** pypi.org/pypi/mcp/json; pypi.org/pypi/fastmcp/json; mã nguồn wheel `mcp-2.3.0` (`server/auth/*`, `server/mcpserver/server.py`, `streamable_http_manager.py`) và `fastmcp_slim-4.1.4` (`server/auth/providers/jwt.py`, `server/dependencies.py`). Trang tài liệu SDK trả 503 khi kiểm.

## 2. OWASP Top 10 for Agentic Applications (2026)

ASI01 Agent Goal Hijack · ASI02 Tool Misuse & Exploitation · ASI03 Identity & Privilege Abuse · ASI04 Agentic Supply Chain Vulnerabilities · ASI05 Unexpected Code Execution · ASI06 Memory & Context Poisoning · ASI07 Insecure Inter-Agent Communication · ASI08 Cascading Failures · ASI09 Human-Agent Trust Exploitation · ASI10 Rogue Agents.

Ngày công bố 2025-12-09 (genai.owasp.org). Danh sách lấy từ kratikal.com (thứ cấp). Trang owasp.org trả 404. Tin cậy TB.

## 3. Keycloak: Standard Token Exchange (V2)

- **Trạng thái:** hỗ trợ chính thức từ 26.2 (keycloak.org, 2025-05-26). Feature `token-exchange-standard:v2` **mặc định bật**, nên `KC_FEATURES=token-exchange-standard` thừa nhưng vô hại. V1 (`token-exchange:v1`) là Preview.
- **Phiên bản:** 26.8.1 (2026-10-13) vá **CVE-2026-97846**: V2 không ép ràng buộc chứng chỉ mTLS; CVSS 6.8. Bản fix nằm ở nhánh 26.6.8, 26.8.1, 27.0.0; nhánh 26.4 không được backport. Repo hiện pin `26.4` (chạy thật: 26.4.7), nên **đề xuất nâng lên 26.8.1**. Ảnh hưởng thấp vì thiết kế chưa dùng mTLS.
- **`act`:** V2 không phát `act`. Subject token có `act`/`may_act` mà không kèm `actor_token` thì bị từ chối. Thiết kế đúng khi dùng `azp`.
- **Luật V2:**
  1. Requester phải là confidential client.
  2. `subject_token` phải có `aud` chứa requester.
  3. Default scope luôn áp dụng; optional scope chỉ áp dụng khi có trong tham số `scope`.
  4. Audience đến từ audience mapper của các scope đang dùng; tham số `audience` chỉ **lọc**, không thêm audience mới được (audience không có sẵn thì bị từ chối).
  5. Executor `downscope-assertion-grant-enforcer` ép chỉ được downscope (hành vi chi tiết chưa rõ).
  6. Không hỗ trợ `resource` (RFC 8707), không hỗ trợ impersonation hay IdP ngoài.
  7. Không tạo user session; refresh token cần bật tuỳ chọn riêng.
- **Chưa xác minh:** tên attribute client `standard.token.exchange.enabled`. Cách kiểm: bật switch trên admin console rồi export realm.

**Nguồn:** keycloak.org/securing-apps/token-exchange; keycloak.org/2025/05/standard-token-exchange-kc-26-2; keycloak.org/server/features; keycloak.org/2026/10/keycloak-2681-released; github.com/keycloak/keycloak/pull/53187; access.redhat.com/security/cve/CVE-2026-97846.

## 4. Advisory LiteLLM (SOLUTION §1)

- **CVE-2026-42208** (SQLi trước xác thực): GHSA-r75f-5x8p-qvmc / PYSEC-2026-391. Ảnh hưởng `>=1.81.16,<1.83.7`; bản vá **1.83.7**; CVSS 4.0 = 9.3; CWE-89. Ngày công bố giữa các nguồn chưa thống nhất (GitHub 20/04, OSV 24/04).
- **03/2026, v1.82.7–1.82.8 chứa mã độc đánh cắp credential:** GHSA-5mg7-485q-xm76 (2026-03-25), OSV MAL-2026-2144. Bản 1.82.8 thêm `litellm_init.pth` chạy mỗi khi khởi động Python. Nguyên nhân gốc theo nguồn thứ cấp: Trivy trong CI không pin, làm lộ token PyPI.
- **21/10/2026, v1.107.0 trên PyPI và Docker:** trang sự cố của LiteLLM (docs.litellm.ai/blog/security-incident-oct-21-2026). Payload là `cook.pth` và `sitecustomize.py`, có backdoor RCE. Nguyên nhân: token GitHub CLI OAuth bị lộ. MAL-2026-2144 được cập nhật 2026-10-29. **Không có nguồn Microsoft nào**, nên SOLUTION §1 cần sửa nguồn và ngày.
- Danh sách advisory LiteLLM đầy đủ lấy qua `api.osv.dev/v1/query` (package `litellm`).

## 5. Exchange 2 audience từ `chat-ui`

- Làm **hai request riêng**: `audience=agent-service&scope=agent:invoke` và `audience=approval-signer&scope=signer:approve`. Không gộp vào một request, vì token sẽ chứa cả hai `aud`.
- Điều kiện:
  - `chat-ui` là confidential client.
  - Token đăng nhập có `aud=chat-ui` (mapper trong default scope).
  - Hai optional scope `agent:invoke` và `signer:approve`, mỗi scope có audience mapper riêng.
- **Chặn `agent-service` exchange sang signer:**
  - Không gán `signer:approve` (default hay optional) cho `agent-service`.
  - Không để mapper `approval-signer` nằm trong realm default scope.
  - Kiểm bằng *Client scopes → Evaluate*.
  - Có thể thử thêm `downscope-assertion-grant-enforcer`, nhưng phải xác nhận nó không chặn các luồng hợp lệ.
- **Chưa xác minh:** giá trị `azp` của token sau exchange V2. Thiết kế dựa vào `azp == chat-ui`, nên spike B **phải** kiểm điểm này.

## 6. `langgraph-checkpoint-postgres` và mã hoá

- `langgraph-checkpoint-postgres` 3.2.0 (2026-10-14) yêu cầu `langgraph-checkpoint>=4.3.0` (bản mới nhất 4.3.1).
- `langgraph.checkpoint.serde.encrypted.EncryptedSerializer.from_pycryptodome_aes()`:
  - Đọc `LANGGRAPH_AES_KEY` dạng **chuỗi thô 16/24/32 byte** (không phải base64).
  - Cần cài thêm `pycryptodome`.
  - Dùng AES-EAX, ciphertext có dạng `nonce||tag||ct`.
- **Không mã hoá mặc định** (mặc định là `JsonPlusSerializer`). Phải truyền `serde` tường minh.
- **Phạm vi mã hoá:**
  - Được mã hoá: `checkpoint_blobs.blob` (chứa `messages`) và `checkpoint_writes.blob`.
  - **Không mã hoá:** `checkpoints.checkpoint` (JSONB), `metadata`, các ID.
- `PostgresSaver.from_conn_string()` bản đồng bộ **không nhận** `serde`, nên phải dùng `PostgresSaver(conn, serde=...)`. Bản async `AsyncPostgresSaver.from_conn_string(..., serde=...)` thì nhận.

```python
serde = EncryptedSerializer.from_pycryptodome_aes()   # LANGGRAPH_AES_KEY
with psycopg.connect(dsn, autocommit=True) as conn:
    saver = PostgresSaver(conn, serde=serde); saver.setup()
```

## 7. License

- **Llama Prompt Guard 2 (86M):**
  - Giấy phép "LLAMA 4 COMMUNITY LICENSE AGREEMENT", model gated trên HF.
  - Có ngưỡng 700M MAU và Acceptable Use Policy.
  - Khi phân phối phải kèm notice.
  - Bản 22M chưa kiểm được (lỗi mạng).
- **bge-m3:** MIT (HF metadata và FlagEmbedding).
- **underthesea** 9.5.0 và **underthesea_core** 3.3.2: **Apache-2.0** (GitHub API, PyPI). Chưa xác minh giấy phép của trọng số NER chế độ deep (`undertheseanlp/vietnamese-ner-*`).

## 8. Redis 8

- **`rename-command`:** vẫn có trong `src/config.c` ở tag 8.10.3 (Cao). ACL vẫn là lớp bảo vệ chính.
- ⚠ **`@search` và Query Engine: mâu thuẫn giữa docs và chạy thật.**
  - Reader (theo redis.io và release notes 8.0): có category `@search`, và `redis:8` đã gộp Query Engine.
  - **Orchestrator chạy thật 2026-10-29 trên image `redis:8` = 8.10.3** (digest `sha256:4764ce37…`):
    - `ACL CAT` không có `search`.
    - `MODULE LIST` chỉ có `vectorset`.
    - Lệnh `FT._LIST` báo `ERR unknown command`.
    - File ACL có `+@search` làm Redis **từ chối khởi động** (`Unknown command or category name in ACL`).
  - Đã xử lý: gỡ `+@search` khỏi `infra/redis/users-cache.acl.tmpl`.
  - **TODO(M4), cần quyết định trước khi làm semantic cache:**
    - (a) dùng image có nạp Query Engine, cần tìm đúng tag hoặc biến thể; hoặc
    - (b) dùng **Vector Sets** (`VADD`/`VSIM`), có sẵn trong `redis:8`.
  - Ghi ADR khi chốt.
- **Cảnh báo ACL (Cao):** từ Redis 8, `+@read`/`+@write` bao gồm cả lệnh Search/JSON. Khi đã có Query Engine thì phải chặn tường minh `-FT.DROPINDEX -FT.ALTER`, hoặc dùng allowlist lệnh `FT.*`.

## Phát hiện khi chạy thật stack (orchestrator, 2026-10-29)

| Vấn đề | Đã sửa |
|---|---|
| `openssl` trên Git Bash/Windows in CRLF, làm `\r` lọt vào 11 file secret, khiến Keycloak import realm lỗi `CTRL-CHAR, code 13` | `gen-secrets.sh`: thêm `tr -d '\r\n'` |
| Prometheus v3.5 không nhận `--web.enable-lifecycle=false` | Bỏ cờ này (mặc định đã tắt) |
| `+@search` không tồn tại trên `redis:8` | Gỡ khỏi ACL, ghi TODO(M4) |
| Image cài package workspace dạng editable sinh `.pth`, bị `check_pth.sh` chặn | `uv sync --no-editable` trong Dockerfile |
| Thiếu module `policy_sidecar.healthcheck` mà compose gọi | Thêm stub (`--require-lock-verified` để TODO(M4)) |

## Tác động lên thiết kế (việc sửa docs)

| Ưu tiên | Vị trí | Thay đổi |
|---|---|---|
| Cao | SOLUTION §1 | Sửa nguồn sự cố 10/2026 thành trang sự cố LiteLLM ngày 21/10 (MAL-2026-2144, v1.107.0); ghi GHSA-r75f (fix 1.83.7) và GHSA-5mg7 |
| Cao | 04 §4.3, compose | Nâng Keycloak 26.4 lên 26.8.1+ (CVE-2026-97846); ghi chú `KC_FEATURES` không cần |
| Cao | 04 §4.2, 07 §8 | BFF gọi hai request exchange tách riêng; luật scope để chặn `agent-service` sang signer; spike B kiểm `azp` |
| Cao | 03 §6.1 | Checkpoint **không** mã hoá mặc định: truyền `EncryptedSerializer` tường minh, thêm `pycryptodome`; nêu rõ phần còn plaintext; key là chuỗi thô 32 byte |
| Cao | 04 §2 Redis | `@search`/Query Engine không có trong `redis:8`; quyết định cho semantic cache (M4) |
| Cao | SOLUTION §5/§8/§10, 02 | API danh tính MCP đã rõ: `fastmcp` `JWTVerifier` hoặc `mcp` 2.3 `MCPServer` + `TokenVerifier` tự viết; `stateless_http=True` |
| TB | SOLUTION §4, `models.lock` | License: Prompt Guard 2 = Llama 4 Community (gated); underthesea = Apache-2.0 |
| Thấp | SOLUTION §9 | Tên OWASP ASI01–ASI10 |

## Còn mở (đưa vào spike)

- Tên attribute `standard.token.exchange.enabled` (export realm sau khi bật switch).
- `azp` sau exchange V2, và hành vi của `downscope-assertion-grant-enforcer` (spike B/C).
- `get_access_token()` trong tool handler của `mcp` 2.3 ở chế độ stateless (spike A).
- Giấy phép trọng số NER deep của underthesea; trang Prompt Guard 2 22M.
