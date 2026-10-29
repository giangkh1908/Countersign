# ADR-001: Chainlit cho MVP, React + TypeScript + BFF ở giai đoạn sau

- **Trạng thái:** **Bị thay thế bởi ADR-002 (2026-10-29).** Trước đó: đã chấp nhận (2026-10-28), sửa đổi v1.2 (2026-10-28) theo `docs/design/DECISIONS-v1.2.md` D0, D1
- **Người quyết định:** chủ dự án

## Bối cảnh
Đây là dự án sản phẩm phát triển tự do. Giá trị cốt lõi nằm ở gateway, MCP và luồng phê duyệt; UI chỉ là một client. Ra được bản v0.1 sớm (milestone M1) quan trọng hơn UX hoàn chỉnh. React + TS cho UX tốt hơn (thẻ duyệt có diff, trang admin, kiểm soát render markdown, CSP) nhưng tốn thêm khoảng 1–2 tuần.

## Quyết định
- **MVP dùng Chainlit** (Python, OAuth Keycloak, `cl.Action` cho nút Duyệt/Sửa/Từ chối).
- **Milestone M6:** chuyển sang **SPA React + TypeScript (Vite) + BFF FastAPI**.

## Ràng buộc để việc chuyển đổi về sau không phải viết lại
1. Mọi logic không thuộc giao diện nằm **ngoài** code Chainlit, trong `packages/ui/src/ui/services/` và `ports/`:
   - **UI không giữ khoá ký** (v1.2, D1). Ký phê duyệt do service `approval-signer` (8310) đảm nhận. UI (Chainlit bây giờ, BFF sau này) chỉ gọi `POST /v1/intents/verify` và `POST /v1/approvals` kèm access token của user. Xem `docs/design/05-approval-flow.md`.
   - `AgentClient` (gọi API SSE của agent): BFF dùng lại.
   - `ApprovalClient` (gọi approval-signer): BFF dùng lại.
   - Session/token handling qua một service riêng, khoá theo `session_id`. Chainlit chỉ là adapter.
2. Code Chainlit chỉ nằm trong `packages/ui/src/ui/adapters/chainlit_app/`. Leak-grep §9 coi `chainlit` là tên vendor.
3. API SSE của agent (`03-agent-ui.md` §1) là **hợp đồng ổn định**: Chainlit hay React đều chỉ là client của nó. Event `interrupt` mang `intent_jws`. UI render thẻ duyệt từ render model mà approval-signer trả về sau khi verify chữ ký, **không** render từ args do agent đưa (WYSIWYS).
4. Token OIDC **luôn ở phía server** (Chainlit backend bây giờ, BFF sau này), không bao giờ xuống trình duyệt.
5. Render markdown trong Chainlit: tắt ảnh/link ngoài nếu cấu hình cho phép (chống exfil). Đây là ghi nhận giới hạn, React sẽ giải quyết triệt để hơn bằng sanitize + CSP.

## Hệ quả
- (+) MVP nhanh, một ngôn ngữ.
- (−) Thẻ duyệt và trang admin hạn chế ở MVP; admin dùng Grafana + admin API (curl/Swagger) tạm thời.
- Kế hoạch React: xem `ROADMAP.md`, milestone M6.
