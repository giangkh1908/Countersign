# Spike A (M0): MCP stateless + kiểm JWT Keycloak + đọc claims trong tool

## Kết luận: ĐẠT

Tiêu chí ROADMAP: "Tool trả `sub` và `department` của caller; sai audience bị 401". Đã chứng minh với `fastmcp` 4.1.4
(`JWTVerifier` + `get_access_token()` + `stateless_http=True`) trên token thật của Keycloak 26.4 (realm `acme`).
Không thử biến thể `mcp` 2.3 `MCPServer` (không bắt buộc, hết time-box); xem khuyến nghị bên dưới.

## Chạy lại
```bash
# 1. Chuẩn bị Keycloak (một lần, qua kcadm trong container; KHÔNG sửa realm-acme.json)
export MSYS_NO_PATHCONV=1   # Git Bash trên Windows
K="docker compose exec -T keycloak /opt/keycloak/bin/kcadm.sh"
$K config credentials --server http://localhost:8080 --realm master --user admin --password "$(cat secrets/kc_admin_password)"
$K set-password -r acme --username an.nguyen --new-password "$SPIKE_A_PASSWORD"   # export SPIKE_A_PASSWORD=<tự chọn> trước
# client test (public, direct grant, fullScopeAllowed=false)
$K create clients -r acme -s clientId=spike-a-cli -s publicClient=true -s directAccessGrantsEnabled=true \
   -s standardFlowEnabled=false -s fullScopeAllowed=false -s enabled=true
$K create clients -r acme -s clientId=spike-a-short -s publicClient=true -s directAccessGrantsEnabled=true \
   -s standardFlowEnabled=false -s fullScopeAllowed=false -s 'attributes."access.token.lifespan"=2'
# scope id lấy từ: $K get client-scopes -r acme --fields id,name
#  acme-claims=21a870df-c335-4d1f-8b49-62ba7d87cefa  docs:read=380ad533-4136-4bbc-9a86-1a29515e60c9  tickets:read=90d2dea0-9565-432f-898f-3751fa7f2901
CID=$($K get clients -r acme -q clientId=spike-a-cli --fields id --format csv --noquotes)
$K update clients/$CID/default-client-scopes/<acme-claims-id> -r acme
$K update clients/$CID/optional-client-scopes/<docs:read-id> -r acme
$K update clients/$CID/optional-client-scopes/<tickets:read-id> -r acme
# spike-a-short: acme-claims + docs:read đều là default scope
# thêm mapper sub (xem phát hiện 1): cho cả hai client
$K create clients/$CID/protocol-mappers/models -r acme -s name=sub -s protocol=openid-connect \
   -s protocolMapper=oidc-sub-mapper -s 'config."access.token.claim"=true'

# 2. Server + 4 ca
W="--no-project --with fastmcp==4.1.4 --with pyjwt[crypto] --with httpx"
uv run $W python spikes/a_mcp_identity/server_fastmcp.py &      # 127.0.0.1:8911/mcp
uv run $W python spikes/a_mcp_identity/run_cases.py
```
Dọn dẹp: xoá 2 client `spike-a-*` (`kcadm.sh delete clients/<id> -r acme`) và đặt lại mật khẩu/xoá credential của `an.nguyen` nếu cần.

## Output thật (rút gọn `www-authenticate` còn đầu dòng)
```
good token claims: sub=3fcb78e6-... iss=http://keycloak.acme.local:8080/realms/acme aud=docs-mcp azp=spike-a-cli dept=['SALES'] clearance=1
[a]  tool whoami -> {'sub': '3fcb78e6-f2de-43fb-94bb-c409a3b8e706', 'dept': ['SALES'], 'clearance': 1, 'azp': 'spike-a-cli', 'aud': 'docs-mcp'}
[a-raw] HTTP 200
[b1 token không có aud docs-mcp (aud=None)]      HTTP 401 Bearer error="invalid_token"
[b2 aud=tickets-mcp]                              HTTP 401 Bearer error="invalid_token"
[c  không token]                                  HTTP 401 www-authenticate='Bearer'
[d1 hết hạn (lifespan 2s, chờ 4s)]                HTTP 401
[d2 sửa payload (sub=evil), giữ chữ ký cũ]        HTTP 401
[d3 ký bằng khoá RSA khác, cùng kid, claims hợp lệ] HTTP 401
[d4 alg=none]                                     HTTP 401
ALL PASS
```
Stateless: response `initialize` không có header `mcp-session-id`; gọi `tools/list` trực tiếp không cần `initialize` vẫn 200.

## Phát hiện
1. **Token của realm hiện KHÔNG có claim `sub`.** Realm import (`realm-acme.json`) tự định nghĩa `clientScopes` nên thiếu scope `basic`
   (chứa mapper `sub` + `auth_time` trong Keycloak 26). Mọi client sẽ bị ảnh hưởng (chat-ui, agent-service...), trong khi contracts/02 `require sub`.
   Spike tạm vá bằng mapper `oidc-sub-mapper` trên client test. **Cần sửa realm-acme.json**: thêm scope `basic` (hoặc `sub` mapper vào `acme-claims`) và gắn default cho mọi client. Không sửa trong spike.
2. **Claim phòng ban thật là `dept`** (mảng, vd `["SALES"]`), không phải `department`; attribute user là `department`, mapper đổi tên thành `dept`. Có thêm `clearance` (số). Không có claim `roles` với user này (fullScopeAllowed=false, không có role).
3. **Audience**: `aud` là chuỗi `"docs-mcp"` (một audience) và chỉ có khi client xin scope `docs:read` (scope `aud-docs-mcp`). Không xin scope này thì token không có `aud` và bị 401. Đúng ý thiết kế (scope quyết định audience).
4. **Issuer host vs container**: token luôn có `iss=http://keycloak.acme.local:8080/realms/acme` kể cả khi lấy qua `localhost:8080` (hostname Keycloak cố định). Verifier phải cấu hình `issuer` đúng chuỗi này, còn `jwks_uri` trỏ địa chỉ truy cập được (host: `localhost:8080`; container: `keycloak:8080` hoặc alias). Tách hai biến cấu hình `KEYCLOAK_ISSUER` và `KEYCLOAK_JWKS_URI`.
5. **fastmcp 4.1.4**: `JWTVerifier` có `jwks_uri, issuer, audience, algorithm, required_scopes, ssrf_safe, jwks_refresh_interval`; từ chối `alg=none`, khoá giả cùng `kid`, payload bị sửa. Đọc claims bằng `get_access_token().claims` (dict đầy đủ, kể cả `dept`/`clearance` tuỳ biến). Lỗi 401 có `error="invalid_token"` nhưng `error_description` là câu chung dài (không phân biệt expired/audience/signature) và không có `resource_metadata`; thiết kế 02 §1.4.3 muốn `expired|audience|signature`, nên cần middleware riêng nếu giữ yêu cầu đó. Không kiểm `exp` leeway (không cần).
6. Khi không token: `WWW-Authenticate: Bearer` trần, body rỗng.

## Khuyến nghị cho `ToolServerHost` (contracts §9.2)
- Thiết kế 02 §2 đã quy định `AuthMiddleware` (PyJWT, adapter `oidc_jwks`) bọc **bên ngoài** `asgi_app()` và không dùng auth của SDK. Spike xác nhận SDK auth là dư: hành vi 401 đạt, nhưng thông điệp lỗi/`resource_metadata`/audit deny không kiểm soát được. Vì vậy **không phụ thuộc `JWTVerifier`**; dùng fastmcp/mcp chỉ làm host giao thức.
- Chọn SDK: **ưu tiên `mcp` 2.3 `MCPServer` làm adapter mặc định** (ít phụ thuộc: fastmcp 4.1.4 kéo theo `fastmcp-slim` + `mcp`), hoặc `fastmcp` nếu cần tiện ích; hai cái đều ổn nên chọn bằng adapter. Chưa chạy thử `mcp` 2.3 (đây là việc còn lại, ~0.5 ngày): xác nhận `get_access_token()` hoạt động trong handler và `streamable_http_app(stateless_http=True)` tách được ASGI app để bọc `AuthMiddleware`.
- Adapter cần: (1) `asgi_app()` trả ASGI stateless để middleware ngoài bọc; (2) truyền `Principal` qua contextvar do `AuthMiddleware` đặt, không qua `get_access_token()` của SDK (tránh khoá SDK); (3) cấu hình tách `issuer` và `jwks_uri`; (4) `required` `exp/iat/iss/aud/sub`, vì `sub` hiện chưa có (phát hiện 1).

> **Cập nhật 2026-10-29 (orchestrator):** phát hiện 1 (thiếu `sub`) đã sửa trong `infra/keycloak/realm-acme.json` (thêm `oidc-sub-mapper` vào scope `acme-claims`), đã xác minh token `chat-ui` có `sub`. Realm được import lại nên client `spike-a-*` và mật khẩu tạm của `an.nguyen` không còn; muốn chạy lại spike thì làm lại bước 1. Quyết định: ADR-003.
