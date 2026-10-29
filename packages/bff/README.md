# acme-bff

BFF: giữ token phía server, phiên Redis mã hoá, CSRF, proxy SSE, luồng phê duyệt (token không bao giờ xuống trình duyệt).

- Import: `bff`; cổng: 8300; mạng: mạng `edge` + `backend`.
- Chạy: `uvicorn bff.main:app` (Dockerfile: `uv sync --package acme-bff`, docs/design/04-infra-data-eval.md §1.5).
- Thiết kế: docs/design/07-web-bff.md §2.1; hợp đồng: docs/design/00-contracts.md §1, §7, §9.
- Trạng thái: khung (skeleton), chưa có logic nghiệp vụ.
