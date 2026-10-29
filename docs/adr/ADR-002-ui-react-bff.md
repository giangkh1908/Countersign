# ADR-002: UI React + TypeScript + BFF ngay từ MVP

- **Trạng thái:** Đã chấp nhận (2026-10-29). **Thay thế ADR-001.**
- **Người quyết định:** chủ dự án
- **Chi tiết kỹ thuật:** `docs/design/DECISIONS-v1.2.md` D15, `docs/design/07-web-bff.md`

## Bối cảnh
ADR-001 chọn Chainlit cho MVP để ra bản đầu nhanh. Sau v1.2, điểm khác biệt chính của sản phẩm là **thẻ phê duyệt WYSIWYS** (render đầy đủ, kiểm soát ký tự, diff trước/sau), và review vòng 2 chỉ ra: (N01) luồng token cần một backend giữ phiên và tự đổi token theo audience; (N03) thẻ duyệt phải hiển thị mọi trường được ký. Chainlit hạn chế đúng ở hai chỗ này (render tuỳ biến, kiểm soát markdown/CSP, quản lý token). Đây là sản phẩm hướng tới chạy thật, không có ràng buộc deadline cứng.

## Quyết định
- Bỏ Chainlit. MVP dùng **SPA React 18 + TypeScript (Vite)** và **BFF FastAPI** (`packages/bff`, cổng 8300).
- Token OIDC, refresh token và token cho approval-signer **chỉ ở BFF**; trình duyệt chỉ có cookie phiên `HttpOnly`.
- API SSE của agent (`03-agent-ui.md` §1) vẫn là hợp đồng ổn định; BFF là client duy nhất của nó.

## Hệ quả
- (+) Thẻ duyệt đúng yêu cầu bảo mật; sanitize markdown + CSP chặt ngay từ MVP; trang admin làm cùng một codebase ở M6.
- (+) Luồng token rõ ràng (D15) và khớp luật token exchange của Keycloak.
- (−) Hai ngôn ngữ (Python + TS), thêm pipeline Node trong CI; M1 dài thêm khoảng 1–1,5 tuần.
- (−) Phải tự làm những thứ Chainlit có sẵn: streaming UI, lịch sử thread, đăng nhập.
