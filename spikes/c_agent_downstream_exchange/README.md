# Spike C (M0): agent-service token exchange tới tài nguyên hạ nguồn

**Kết luận: ĐẠT, giữ phương án chính (RFC 8693, Keycloak 26.4 standard token exchange V2). Không chuyển sang phương án B.**

`agent-service` đổi token `aud=agent-service` của user lấy token `aud=tickets-mcp` / `aud=llm-gateway` (`azp=agent-service`). Các claim `sub`, `dept`, `clearance` được giữ nguyên. Resource server phân biệt được đích nhờ `aud`. Cấu hình `agent-service` trong `realm-acme.json` dùng được ngay, không cần sửa gì để spike chạy. Có hai đề xuất siết lại, xem mục 6.

Lần chạy cuối: `79/79 PASS` (`output.txt`), cộng một ca bổ sung G do lead chạy riêng.

## 1. Verdict theo tiêu chí

| # | Tiêu chí | Verdict | Bằng chứng (`output.txt`) |
|---|---|---|---|
| 1 | Exchange `aud=agent-service` → `tickets-mcp` (`tickets:read`, `tickets:write`, cả hai) và → `llm-gateway` (`llm:invoke`), giữ `sub`/`dept`/`clearance` | **ĐẠT** | Mục A: chi.le 4 tổ hợp, tam.vu 2 đích. Mọi token có `azp=agent-service`, không có `act`, `exp−iat=300` |
| 2 | Ca âm: scope không được gán, subject `aud` không chứa agent-service, token hết hạn / bị sửa / chữ ký rác, secret sai | **ĐẠT** | Mục C: 400 `invalid_scope`, 403 `access_denied`, 400 `Invalid token`, 401 `unauthorized_client` |
| 3 | tickets-mcp (MCP, PyJWT/JWKS) và gateway giả chấp nhận token đã exchange; từ chối token gốc `aud=agent-service` và token của đích kia | **ĐẠT** | Mục D: 200 trả đúng danh tính; 401 với `reason=audience/signature/expired/scope/api_key` |
| 4 | Latency và quyết định cache | **ĐẠT** | Mục E: exchange p50 ≈ 10–12 ms, p95 ≈ 18–21 ms (keep-alive, 127.0.0.1). Kết luận: **có cache**, xem mục 4 |
| 5 | Phương án B chạy thử và so sánh | **ĐẠT** (chạy được). **Không chọn** làm phương án chính | Mục F/F2: B hoạt động, nhưng chứng minh được replay chéo dịch vụ và agent "dựng" được danh tính user bất kỳ |
| 6 | Đề xuất port `TokenBroker` | **ĐẠT** (đề xuất) | Mục 5; prototype ở `broker.py` |

## 2. Cách chạy

```bash
cd D:/AI_EXAMPLE
bash spikes/c_agent_downstream_exchange/run.sh    # ~2,5 phút; tự setup → chạy → cleanup + status (trap)
```

- `run.sh`:
  - Sinh `SPIKE_C_PW` (mật khẩu tạm cho chi.le/tam.vu) và `SPIKE_C_SECRET` (secret client tạm) bằng `openssl rand`.
  - Gọi `kc_setup.sh setup|status|cleanup` qua `MSYS_NO_PATHCONV=1 docker compose exec -T -e ... keycloak bash -s <cmd> < kc_setup.sh`, dùng config kcadm riêng `/tmp/kcadm-spike-c.config`.
  - Chạy `run_cases.py` bằng `uv run --no-project --with fastmcp==4.1.4 --with "pyjwt[crypto]" --with httpx --with uvicorn --with starlette`.
- Secret agent-service đọc từ `secrets/kc_agent_client_secret` lúc chạy. Không có secret hay mật khẩu nào nằm trong file.
- Output chỉ in claims đã decode, hoặc dạng `eyJ...(len=N)`. Đã grep `eyJ[A-Za-z0-9_-]{40,}` và secret agent-service trên toàn thư mục: 0 kết quả.
- Ca G (bổ sung): `extra_no_service_account.sh` + `extra_no_service_account.py`. Đã chạy tay với env tương tự, output nối vào cuối `output.txt`.

**Cách lấy subject token `aud=agent-service`:** không đụng `chat-ui`. Tạo client tạm `spike-c-login` với các thuộc tính: confidential, direct grant, `standard.token.exchange.enabled=true`, `fullScopeAllowed=false`, default `acme-claims`, audience mapper trỏ vào chính nó. Scope có sẵn `agent:invoke` được **liên kết** vào client này làm optional, scope đó không bị sửa.

Luồng có hai bước:
1. Direct grant cho chi.le, ra token `aud=spike-c-login`. Token này đóng vai token đăng nhập của chat-ui.
2. `spike-c-login` exchange `audience=agent-service&scope=agent:invoke`, ra subject token `aud=agent-service, azp=spike-c-login, scope="acme-claims agent:invoke"`. Token này đóng vai token BFF gửi cho agent.

## 3. Kết quả chính (trích output thật)

**A. Token đã exchange** (chi.le, sub `5262e5ff…`, dept `['SALES']`, clearance 3)

| Request | `aud` | `azp` | `scope` | `act` | `exp−iat` | refresh_token |
|---|---|---|---|---|---|---|
| `audience=tickets-mcp&scope=tickets:read` | `tickets-mcp` | `agent-service` | `tickets:read acme-claims` | không | 300 | không |
| `…&scope=tickets:write` | `tickets-mcp` | `agent-service` | `tickets:write acme-claims` | không | 300 | không |
| `…&scope=tickets:read tickets:write` | `tickets-mcp` | `agent-service` | `tickets:write tickets:read acme-claims` | không | 300 | không |
| `audience=llm-gateway&scope=llm:invoke` | `llm-gateway` | `agent-service` | `acme-claims llm:invoke` | không | 300 | không |

- `sub`, `dept`, `clearance` và `sid` khớp với subject token và token đăng nhập. tam.vu (clearance 0) cũng khớp.
- `issued_token_type=urn:ietf:params:oauth:token-type:access_token`, `expires_in=300`.

**B. Thăm dò hành vi Keycloak**
- Có `audience` nhưng thiếu `scope`, hoặc `scope` không map ra audience đó: `400 invalid_request "Requested audience not available: tickets-mcp"`. Vậy **audience chỉ đạt được qua optional scope có audience mapper mà client requester được gán**. Đây cũng là cơ chế khiến agent-service không lấy được `aud=approval-signer` (Spike B kiểm trực tiếp).
- Có `scope=tickets:read` nhưng không truyền `audience`: 200, `aud=tickets-mcp`, do mapper của scope.
- `audience=tickets-mcp` kèm `scope="tickets:read llm:invoke"`: 200, `aud=tickets-mcp`, nhưng `scope` vẫn chứa `llm:invoke`. Trong `output.txt`, dòng này mang nhãn cũ "hai audience …" là nhãn sai: request thật chỉ có một `audience`. Nhãn đã được sửa trong `run_cases.py`.
- Lặp tham số `audience` hai lần: 200, `aud=['tickets-mcp','llm-gateway']`. **Cấm trong broker:** mỗi request chỉ một audience.

**C. Ca âm (lỗi nguyên văn)**
- Scope không được gán, gồm `agent:invoke`, `analytics:write`, `admin`, và tổ hợp `tickets:read agent:invoke`: `400 invalid_scope "Invalid scopes: …"`. Cả request bị từ chối, không có chuyện lọc bớt scope.
- Subject `aud=spike-c-login`: `403 access_denied "Client is not within the token audience"`.
- Subject hết hạn (client `spike-c-short`, lifespan 15 s), subject bị sửa payload, chữ ký rác: `400 invalid_request "Invalid token"`.
- Secret sai: `401 unauthorized_client "Invalid client or Invalid client credentials"`.

**D. Resource servers** (`resource_servers.py`)
- tickets-mcp ở `127.0.0.1:8931/mcp`: fastmcp 4.1.4 stateless, bọc bởi middleware ASGI PyJWT theo ADR-003.
- Gateway giả ở `127.0.0.1:8932/v1/whoami`: kiểm API key và `X-Acme-User-Token` `aud=llm-gateway`, theo contracts §3.4.
- Cả hai chấp nhận token đúng đích và trả về danh tính user.
- tickets-mcp trả 401 với: token gốc `aud=agent-service` (`audience`), token llm-gateway (`audience`), token bị sửa hoặc chữ ký rác (`signature`), không có token (`missing_bearer`), token chỉ có `tickets:write` (`scope`), token hết hạn (`expired`).
- Gateway trả 401 với: token gốc (`audience`), token tickets-mcp (`audience`), API key sai (`api_key`), token bị sửa (`signature`).

**G. (bổ sung) `serviceAccountsEnabled=false`**
- Client tạm `spike-c-nosa` không có service account vẫn exchange được: 200, `aud=tickets-mcp`, giữ `sub`/`dept`/`clearance`.
- `client_credentials` trên client này bị chặn: `401 unauthorized_client "Client not enabled to retrieve service account"`.
- Giới hạn của ca này: client tự exchange token của chính nó, không phải token của client khác. Kết quả đủ để kết luận exchange V2 không cần service account.

### Phát hiện cần đưa vào thiết kế
1. **Token đã exchange không bị chặn bởi `exp` của subject.** Subject sống 15 s, nhưng token đổi ra vẫn sống 300 s (`exp` vượt subject 285 s). Lifespan lấy theo client requester (agent-service). Ở ca A, hai `exp` trùng nhau chỉ vì cùng lifespan mặc định 300 s.
2. **Không có `act`.** Bên thực hiện chỉ nhận ra qua `azp=agent-service`. Delegation `act` của Keycloak đang ở Preview và tắt mặc định, nên giữ cách dùng `azp` như contracts đã dự liệu.
3. **`scope` luôn chứa `acme-claims`.** Server phải kiểm scope theo kiểu "chứa", không so khớp nguyên chuỗi.
4. **`agent-service` có service account** (ca F). Với cờ này, agent tự lấy được token `aud=tickets-mcp`, kể cả `tickets:write`, có `azp=agent-service` hợp lệ nhưng `sub` là service account và **không có `dept`/`clearance`**. Nếu MCP chỉ kiểm `aud`/`azp`/`scope` thì sẽ nhận token này. Ca G cho thấy phương án chính không cần service account, nên đề xuất tắt cờ này (mục 6).

## 4. Latency và cache

| Nhóm (n=20 trừ khi ghi khác) | p50 | p95 | min | max |
|---|---|---|---|---|
| Exchange tickets-mcp, keep-alive, `127.0.0.1` | 12,4 | 20,8 | 9,9 | 31,7 |
| Exchange llm-gateway, keep-alive, `127.0.0.1` | 10,2 | 18,2 | 9,4 | 20,6 |
| Exchange tickets-mcp, client mới mỗi lần | 27,7 | 36,3 | 24,6 | 37,5 |
| Exchange llm-gateway, client mới mỗi lần | 25,8 | 32,5 | 24,1 | 34,2 |
| client_credentials (B), keep-alive, `127.0.0.1` | 11,4 | 16,6 | 9,1 | 16,7 |
| `CachingTokenBroker` (1 miss + 19 hit) | 0,0 | 0,0 | 0,0 | 55,7 |
| Verify JWT RS256, JWKS đã cache (n=200) | 0,1 | 0,2 | 0,1 | 1,0 |
| tickets `/mcp` whoami end-to-end | 5,2 | 5,8 | 4,8 | 7,3 |

Đơn vị: ms. Số đo keep-alive qua `localhost` cao hơn khoảng 40 ms (p50 52 ms). Đây là artifact của Windows (dual-stack và delayed-ACK), không phải chi phí của Keycloak. Cấu hình compose dùng tên DNS `keycloak` nên không bị ảnh hưởng, nhưng adapter vẫn nên dùng `httpx.AsyncClient` dùng chung.

**Quyết định cache: CÓ cache**, theo contracts §9.2. Lý do:
- Một lượt agent gọi 2–4 audience, mỗi audience nhiều lần (LLM call, tool call). Không cache thì tốn khoảng 10–30 ms và một request tới Keycloak cho mỗi lần gọi.
- Keycloak thành điểm nghẽn: mọi tool call phụ thuộc vào nó.

Cách cache:
- Khoá `(sub, audience, sorted scopes)`.
- TTL = **`min(exp_token_mới, exp_subject) − 30 s`**. Đây là điều chỉnh so với contracts, xuất phát từ phát hiện 1: không để token hạ nguồn sống lâu hơn token user đã đưa cho agent.
- Không cache `tickets:write`.
- In-process, LRU tối đa 2000 mục.
- Khi gặp 401 từ hạ nguồn thì xoá các mục của `sub` đó.

## 5. Phương án chính và phương án B

Phương án B được chạy thử như sau:
- agent dùng `client_credentials` lấy token `aud=tickets-mcp`, `azp=agent-service`, `sub` = service account `218367d9…`, không có `dept`.
- agent gửi kèm `X-Acme-User-Token` là token gốc `aud=agent-service`.
- `/mcp-b` verify cả hai token và lấy danh tính từ header: trả đúng chi.le.
- Các ca âm của B đều đạt: thiếu header, header sai `aud`, header hết hạn, header bị sửa, Bearer là token user.

| Tiêu chí | Chính: token exchange | B: client-credentials + `X-Acme-User-Token` |
|---|---|---|
| Ràng buộc đích (`aud`) | Mỗi token chỉ dùng cho một đích. Token tickets bị gateway từ chối (D, F2) | Token user `aud=agent-service` được **cả** `/mcp-b` lẫn gateway-B chấp nhận (F2), tức replay chéo dịch vụ |
| Confused deputy / mạo danh | Keycloak chỉ cấp khi có subject token hợp lệ chứa agent-service trong `aud`. Scope và audience bị giới hạn theo client scope của agent | Với credentials agent, **bất kỳ** token user nào cũng "dựng" được danh tính đó ở mọi hạ nguồn (F2: cùng cc-token, đổi header là ra chi.le hoặc tam.vu). Quyền tool lấy từ scope của *agent*, không phải của user |
| Token user có `aud` không khớp | Resource server từ chối (chuẩn RFC 9700 §2.3) | Resource server **buộc phải** nhận token không dành cho mình (`aud=agent-service`). Đây đúng là "token passthrough" mà đặc tả MCP cấm: "MCP servers MUST NOT accept any tokens that were not explicitly issued for the MCP server" |
| Lộ token | Token hạ nguồn bị lộ chỉ dùng được ở một đích, trong ≤ 300 s | Token user bị lộ ở một MCP dùng được ở mọi MCP và gateway |
| Độ phức tạp | Một token mỗi đích. Server verify **một** JWT. Cấu hình realm có sẵn | Hai token mỗi request. Mọi server cần verify **hai** JWT với hai bộ luật `aud`/`azp`. Phải đồng bộ allowlist `azp` của user token ở mọi nơi |
| Latency | ≈ 10–12 ms mỗi miss, cache được | ≈ 11 ms, cc-token cache được theo (audience, scope) không cần `sub` |
| Khớp D13/D15/contracts | Khớp: agent chỉ exchange tới 3 MCP + gateway, không tới signer; `azp` thay cho `act` | Lệch: gateway chỉ tin `X-Acme-User-Token` có `aud=llm-gateway` (contracts §3.4), còn MCP sẽ phải nhận token `aud=agent-service` (trái ADR-003, 02 §1.4) |

**Khuyến nghị:** chọn phương án chính. Giữ `client_credentials_with_user_token` chỉ như phương án dự phòng, có ghi rõ giới hạn và **không cài adapter khi chưa cần**. Nếu sau này buộc phải dùng B, hai điều kiện bắt buộc:
- Resource server chỉ nhận user token có `azp ∈ {chat-ui}`.
- Ghi audit cả hai `sub`.

## 6. Đề xuất (chưa áp dụng)

### 6.1 Diff cho `infra/keycloak/realm-acme.json`

```diff
     {
       "clientId": "agent-service",
       "name": "agent-service",
       ...
       "standardFlowEnabled": false,
       "directAccessGrantsEnabled": false,
-      "serviceAccountsEnabled": true,
+      "serviceAccountsEnabled": false,
       "fullScopeAllowed": false,
       "attributes": {
-        "standard.token.exchange.enabled": "true"
+        "standard.token.exchange.enabled": "true",
+        "access.token.lifespan": "300"
       },
```

- **`serviceAccountsEnabled: false`.** Không thành phần nào trong thiết kế dùng service account của agent-service: gateway dùng API key, MCP dùng token user đã exchange. Ca G chứng minh exchange vẫn chạy khi tắt cờ này, và tắt cờ thì chặn được việc agent tự cấp token không gắn user, kể cả `tickets:write` (phát hiện 4). Kéo theo cần sửa chữ "service account" ở contracts §4 (bảng client) và 04 §4.2 (dòng 1072, 1122). Chỉ bật lại nếu chuyển sang B.
- **`access.token.lifespan: "300"`.** Ghim tường minh lifespan của token hạ nguồn, để việc nới `accessTokenLifespan` của realm sau này không kéo dài token agent theo (phát hiện 1).
- Không cần đổi gì cho `tickets-mcp`, `llm-gateway`, các scope `llm:invoke`/`tickets:*` hay `optionalClientScopes` của agent-service.
- Phòng thủ bổ sung ở resource server, không phải thay đổi realm: `TokenVerifier` của MCP và gateway **bắt buộc có `dept` và `clearance`** cho token `azp=agent-service`. Thiếu thì trả 401.

### 6.2 Port `TokenBroker` (`acme_common`, đặt cùng `TokenVerifier`)

```python
@dataclass(frozen=True)
class AccessToken:
    value: str                      # __repr__ che giá trị
    audience: str
    scopes: frozenset[str]
    expires_at: float               # epoch, đã min với exp của subject
    sub: str
    extra_headers: Mapping[str, str] = field(default_factory=dict)  # phương án B: {"X-Acme-User-Token": ...}

class TokenBrokerError(Exception):          # .status, .error, .description (không chứa token)
    ...

class TokenBroker(abc.ABC):
    @abc.abstractmethod
    async def token_for(self, principal: Principal, user_token: str,
                        audience: str, scopes: frozenset[str]) -> AccessToken: ...
```

Thay đổi so với contracts §9.2: thêm `principal`, là kết quả của `TokenVerifier.verify` mà agent đã có sẵn. Cache lấy `sub` và `exp` của subject từ `principal`, không decode lại token.

| Lớp | File | Ghi chú |
|---|---|---|
| `OAuthTokenExchangeBroker` | `adapters/oauth_token_exchange.py` | RFC 8693, form `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`, **một** `audience` và scope tương ứng mỗi request. Kiểm hậu điều kiện: `aud == audience`, `scopes ⊆ requested ∪ {acme-claims}`; sai thì raise. Dùng `RetryingHttpClient` theo composition. Map `invalid_scope`/`access_denied`/`invalid_request` sang `TokenBrokerError` và từ đó sang `error{auth}` |
| `ClientCredentialsWithUserTokenBroker` | `adapters/client_credentials_with_user_token.py` | Chỉ là dự phòng (mục 5), **chưa cài** |
| `StaticTokenBroker` | `testing/` | Fake cho test |
| `CachingTokenBroker(inner, skew=30, max_entries=2000, no_cache_scopes={"tickets:write"})` | `decorators/caching.py` | Khoá `(principal.sub, audience, sorted scopes)`. TTL `min(token.exp, principal.exp) − skew`. Single-flight `asyncio.Lock` theo khoá. Có `evict(sub)`. Với B chỉ cache cc-token, không cache header user |
| `MeteredTokenBroker` | `decorators/metrics.py` | Histogram latency, đếm hit/miss/lỗi theo `audience` |

- Factory: `{"oauth_token_exchange": "acme_common.auth.adapters.oauth_token_exchange:OAuthTokenExchangeBroker", ...}`, lazy import.
- Đề bài gọi adapter là `keycloak_token_exchange`. Tôi đề xuất **giữ tên `oauth_token_exchange` như contracts**, vì RFC 8693 là chuẩn mở, không phải API riêng của vendor, phù hợp quy tắc "không bọc chuẩn mở / tên vendor chỉ ở settings".

### 6.3 Nội dung ADR (đề xuất `docs/adr/ADR-005-agent-downstream-token.md`)
- **Trạng thái:** Đề xuất, sau Spike C (M0). Bằng chứng: README này và `output.txt`.
- **Bối cảnh:** agent cần gọi gateway và 3 MCP bằng danh tính user. Có hai lựa chọn: RFC 8693 exchange, hoặc client-credentials kèm `X-Acme-User-Token`.
- **Quyết định:**
  1. Dùng Keycloak standard token exchange V2. Mỗi đích một request, mỗi request một `audience` và scope tương ứng.
  2. Bên thực hiện được nhận diện qua `azp=agent-service`, không dùng `act`, vì Keycloak V2 không phát `act` và delegation còn ở Preview.
  3. Quyền exchange tới từng đích được ép bằng optional client scope có audience mapper gán cho agent-service. Không có scope thì Keycloak trả `Requested audience not available`.
  4. `CachingTokenBroker` với TTL `min(exp, exp_subject) − 30 s`; không cache `tickets:write`.
  5. Tắt service account của agent-service và ghim `access.token.lifespan=300`.
  6. Resource server kiểm `iss`/`aud`/`exp`/chữ ký/scope theo kiểu "chứa", và bắt buộc có `dept`/`clearance`.
- **Phương án bị bác:** B (client-credentials + header). Lý do: replay chéo dịch vụ, agent dựng được danh tính bất kỳ, buộc MCP nhận token không dành cho nó (vi phạm đặc tả MCP về token passthrough và RFC 9700 §2.3). B chỉ giữ làm dự phòng.
- **Hệ quả:**
  - Contracts §4 và §9.2 cần cập nhật: chữ ký `token_for` thêm `principal`, TTL dùng `min`, bỏ chữ "service account".
  - 04 §4.2 cập nhật JSON realm.
  - Thêm test hồi quy: token `azp=agent-service` thiếu `dept` thì nhận 401.
  - Keycloak trở thành phụ thuộc nóng của mọi tool call. Rủi ro này được giảm bằng cache và circuit breaker.

## 7. Thay đổi trên Keycloak và trạng thái dọn dẹp
- Tạm thời có ba client: `spike-c-login`, `spike-c-short` (`access.token.lifespan=15`, liên kết thêm optional `tickets:read`) và `spike-c-nosa` (ca G, `serviceAccountsEnabled=false`). Client tạm chỉ được *liên kết* scope `agent:invoke`/`tickets:read`, scope đó không bị sửa.
- Mật khẩu tạm của chi.le và tam.vu: baseline 0 credential, script dừng nếu thấy credential có sẵn.
- **Đã dọn:** `status` sau cleanup (lead chạy lại độc lập) ghi `spike-c clients: []`, `credentials chi.le=0 tam.vu=0`.
- sha256 JSON của `agent-service`, `tickets-mcp`, `llm-gateway` và các scope `llm:invoke`, `tickets:read`, `tickets:write`, `agent:invoke` trùng nhau trước và sau.
- Không đụng `chat-ui`, `approval-signer`, `signer:approve`, an.nguyen, binh.tran. Không thử exchange tới approval-signer. Không restart hay reimport.

## 8. File
- `README.md`, `output.txt`
- `run.sh`, `kc_setup.sh`, `run_cases.py`, `resource_servers.py`, `broker.py`
- `extra_no_service_account.sh`, `extra_no_service_account.py`
