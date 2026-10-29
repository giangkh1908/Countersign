# approval-signer

Giữ khóa riêng ES256 ký approval token; xác minh intent JWS của tickets-mcp; trả render model. Nhỏ có chủ đích (<= ~300 dòng), không Redis/DB.

- Cổng: 8310 (không expose host)
- Mạng docker: `core` only, không egress
- Tài liệu: `docs/design/05-approval-flow.md`, `docs/design/00-contracts.md` §1, §4.1, §7
