# ADR-002: UI React + TypeScript + BFF ngay từ MVP

- **Trạng thái:** Đã chấp nhận (2026-10-29). Thay thế quyết định dùng Chainlit.
- **Người quyết định:** chủ dự án
- **Chi tiết kỹ thuật:** [`design/contracts.md`](../design/contracts.md) (mục 2 luồng token, mục 9.4 frontend), `packages/bff`

## Bối cảnh
Bản đầu chọn Chainlit (ADR-001, đã xoá, xem git tag `backup/pre-prune-20261101`) cho MVP để ra bản đầu nhanh. Sau v1.2, điểm khác biệt chính của sản phẩm là **thẻ phê duyệt WYSIWYS** (render đầy đủ, kiểm soát ký tự, diff trước/sau), và review vòng 2 chỉ ra: luồng token cần một backend giữ phiên và tự đổi token theo audience; thẻ duyệt phải hiển thị mọi trường được ký. Chainlit hạn chế đúng ở hai chỗ này (render tuỳ biến, kiểm soát markdown/CSP, quản lý token). Đây là sản phẩm hướng tới chạy thật, không có ràng buộc deadline cứng.

## Quyết định
- Bỏ Chainlit. MVP dùng **SPA React 18 + TypeScript (Vite)** và **BFF FastAPI** (`packages/bff`, cổng 8300).
- Token OIDC, refresh token và token cho approval-signer **chỉ ở BFF**; trình duyệt chỉ có cookie phiên `HttpOnly`.
- API SSE của agent (`contracts.md` mục 7) vẫn là hợp đồng ổn định; BFF là client duy nhất của nó.

## Hệ quả
- (+) Thẻ duyệt đúng yêu cầu bảo mật; sanitize markdown + CSP chặt ngay từ MVP.
- (+) Luồng token rõ ràng và khớp luật token exchange của Keycloak.
- (−) Hai ngôn ngữ (Python + TS), thêm pipeline Node trong CI; M1 dài thêm khoảng 1–1,5 tuần.
- (−) Phải tự làm những thứ Chainlit có sẵn: streaming UI, lịch sử thread, đăng nhập.
