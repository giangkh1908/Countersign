# ADR-003: MCP server — xác thực bằng middleware riêng, SDK chỉ để host giao thức

- **Trạng thái:** Đã chấp nhận (2026-10-29), sau Spike A (M0).
- **Người quyết định:** orchestrator; chủ dự án review
- **Bằng chứng:** `spikes/a_mcp_identity/README.md`, `docs/research/05-m0-verification.md` §1
- **Liên quan:** contracts §9.2 (`ToolServerHost`), `docs/design/02-mcp-servers.md` §1.4

## Bối cảnh
Spike A dựng một MCP server Streamable HTTP ở chế độ stateless bằng `fastmcp` 4.1.4, kiểm JWT thật của Keycloak (`aud=docs-mcp`). Spike **đạt** đủ các ca:
- Token hợp lệ: đọc được claims trong tool.
- Sai `aud` hoặc không có `aud`: 401.
- Không có token: 401.
- Token hết hạn, payload bị sửa, ký bằng khoá giả cùng `kid`, `alg=none`: 401.

Phát hiện:
1. Lỗi 401 của SDK là một câu chung, không phân biệt `expired|audience|signature` và không có `resource_metadata`, trong khi thiết kế 02 §1.4.3 yêu cầu cả hai.
2. `get_access_token()` gắn chặt với từng SDK. `mcp` 2.3 và `fastmcp` có API khác nhau, và trong `mcp` 2.x `FastMCP` đã đổi tên thành `MCPServer`.
3. Issuer trong token luôn là `http://keycloak.acme.local:8080/realms/acme`, kể cả khi lấy JWKS qua `localhost`.
4. Realm thiếu mapper `sub`, vì `realm-acme.json` định nghĩa lại `clientScopes` nên mất scope built-in `basic`. **Đã sửa** bằng cách thêm `oidc-sub-mapper` vào scope `acme-claims`, và đã xác minh trên token thật.

## Quyết định
1. **Xác thực không dùng auth của SDK.** Mỗi MCP server bọc `ToolServerHost.asgi_app()` bằng một `AuthMiddleware` (ASGI) dùng port `TokenVerifier` của `acme_common` (adapter `oidc_jwks`, PyJWT). Middleware:
   - Kiểm `iss`, `aud`, `exp`, `iat`, `sub`, `azp` (theo `MCP_ALLOWED_AZP`) và chữ ký với thuật toán trong allowlist.
   - Trả 401 có `error_description` thuộc `expired|audience|signature|malformed` và `resource_metadata`.
   - Đặt `Principal` vào một contextvar để tool handler đọc.
2. **SDK chỉ để host giao thức** (stateless, `stateless_http=True`). Adapter của `ToolServerHost`:
   - `mcp_sdk` (`mcp` 2.3, `MCPServer.streamable_http_app(stateless_http=True)`) là **mặc định**, vì ít dependency hơn.
   - `fastmcp` (4.1.4, đã chứng minh trong Spike A) là adapter thay thế.
   - **Điều kiện:** việc đầu tiên của M1 (≤ 0,5 ngày) là chạy thử `mcp` 2.3 stateless và lấy được ASGI app để bọc middleware. Không đạt thì đổi mặc định sang `fastmcp` và cập nhật ADR này.
3. Cấu hình tách hai biến:
   - `KEYCLOAK_ISSUER`: chuỗi so khớp với claim `iss`.
   - `KEYCLOAK_JWKS_URI`: URL lấy khoá, mặc định suy ra từ issuer. Cần tách vì ở dev, host và container có thể thấy Keycloak qua hai tên khác nhau.
4. Claim phòng ban là `dept` (mảng) và `clearance` (số), đúng contracts §4. Không dùng `department`.

## Hệ quả
- (+) Đổi SDK MCP không ảnh hưởng xác thực hay business logic. Thông báo lỗi 401 đúng thiết kế 02.
- (+) Cùng một `TokenVerifier` dùng chung cho gateway, agent, bff và MCP (D16).
- (−) Tự viết và tự test middleware khoảng 100 dòng, với các ca âm giống Spike A.
- (−) Còn phụ thuộc kết quả kiểm `mcp` 2.3 ở đầu M1.
