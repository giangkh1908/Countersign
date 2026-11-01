# infra/keycloak

`realm-acme.json` được import khi Keycloak khởi động (`start-dev --import-realm`). Bằng chứng về token exchange: [ADR-005](../../docs/adr/ADR-005-token-flow.md).

Có: realm `acme`, 6 realm role, client scope `acme-claims` (dept, clearance, roles) và các scope audience, các client `chat-ui`, `agent-service`, `llm-gateway`, `docs-mcp`, `tickets-mcp`, `approval-signer`, 16 user mẫu có `department`, `clearance`, `employee_id`. Bảng client và scope: [`contracts.md`](../../docs/design/contracts.md) §2–§3.

User không có mật khẩu trong JSON (chưa có script đặt mật khẩu; E2E tự đặt qua Admin API). Secret client dùng `${BFF_OIDC_CLIENT_SECRET}` và `${AGENT_KC_CLIENT_SECRET}`.

Đổi realm thì xoá volume Keycloak để import lại.
