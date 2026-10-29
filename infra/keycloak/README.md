# infra/keycloak

`realm-acme.json` được import khi Keycloak khởi động (`start-dev --import-realm`). Nguồn: `docs/design/04-infra-data-eval.md` §4.1–4.5.
File này chỉ là **khung hợp lệ JSON**; chưa chạy thử với Keycloak thật.

Có: realm `acme`, 6 realm role, client scope (`acme-claims` với mapper dept/clearance/roles, các scope audience), 7 client
(`chat-ui`, `agent-service`, `llm-gateway`, `docs-mcp`, `tickets-mcp`, `analytics-mcp`, `approval-signer`), 16 user mẫu (§4.5)
với thuộc tính `department`/`clearance`/`employee_id`, user profile khai báo (user không tự sửa được thuộc tính).
Secret client dùng `${BFF_OIDC_CLIENT_SECRET}` / `${AGENT_KC_CLIENT_SECRET}` (compose `export` từ Docker secret trước khi `kc.sh`).

User **không có mật khẩu** trong JSON. `data/seed_keycloak.py` đặt mật khẩu ngẫu nhiên qua Admin API (`secrets/demo_users.csv`).

## TODO spike M0 (chưa xác minh)

- Tên feature/thuộc tính token exchange theo bản Keycloak: cần >= 26.2 (Standard Token Exchange); `KC_FEATURES=token-exchange-standard`
  và `standard.token.exchange.enabled` có thể khác ở 26.4. Đối chiếu release notes lúc pin.
- Quyền exchange: chỉ `chat-ui` -> `agent-service`/`approval-signer`; `agent-service` -> `llm-gateway`/MCP (không tới `approval-signer`).
  JSON chưa mã hoá luật này (audience mapper theo scope + `fullScopeAllowed=false` là phần có sẵn); kiểm bằng `eval/security/test_token_exchange.py`.
- Realm import có thay thế `${ENV}` trong `secret` hay không ở bản pin; client scope tự định nghĩa có làm mất scope mặc định
  (`profile`, `email`, `roles`) hay không (hiện không tham chiếu scope built-in nào).
- Cấu hình declarative user profile (`components.UserProfileProvider`): kiểm định dạng, validator `integer` cho `clearance`,
  và `unmanagedAttributePolicy`.
- Audience mapper `aud-chat-ui` trên chính `chat-ui` có đủ cho luật exchange V2 không (spike C).
- `sslRequired: external` -> dev trên `keycloak.acme.local` (không phải localhost) có thể đòi HTTPS ở admin console; nếu vướng đặt `none` cho dev.
