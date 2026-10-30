# data/ — dữ liệu giả lập "ACME Việt Nam"

Thiết kế: `docs/design/04-infra-data-eval.md` PHẦN B (§7–§8). Mọi PII là giả.

| Thư mục | Nội dung |
|---|---|
| `generator/` | Generator ACME có seed (`20261028`), chỉ dùng stdlib, không gọi LLM: 30 tài liệu, 100 ticket, analytics nhỏ, user từ realm |
| `tests/` | Test offline của generator (`uv run pytest data/tests`) |
| `load_seed.sh` | Nạp SQL seed vào Postgres trong compose (idempotent) |
| `corpus/` | Corpus độc cho E4 (>= 50 tài liệu, 8 kỹ thuật injection, có ground truth) |
| `pii_testset/` | Tập test PII viết tay (tập chính cho bộ lọc PII, R11/R13) |
| `generated/` | Đầu ra của generator, đã gitignore |

## Chạy seed (M1)

```bash
uv run python -m data.generator                  # -> data/generated/ (xoá và ghi lại toàn bộ)
docker compose up -d postgres                    # init schema chạy khi pg_data còn trống
bash data/load_seed.sh                           # nạp vào gateway/knowledge/tickets/analytics
bash infra/postgres/verify/run.sh                # kiểm chứng RLS/quyền trên DB thật (assert)
```

Tuỳ chọn: `--seed N`, `--out DIR`, `--realm FILE`, `--sub-map FILE`.
Cùng seed => đầu ra giống hệt từng byte (xem `manifest.json`, có sha256 từng file, không có timestamp).
Nạp lại nhiều lần là an toàn (`INSERT ... ON CONFLICT (id) DO UPDATE`). Seed chạy bằng superuser
`postgres` nên bỏ qua RLS ở bước nạp; `-p <project>` qua biến `COMPOSE="docker compose -p <project>"`.

## Nội dung seed

- **Phòng ban dữ liệu:** `ALL` (6 tài liệu), `SALES`, `HR`. Tài liệu: 30 (c0=5, c1=11, c2=8, c3=6; xem `documents.jsonl`),
  mỗi tài liệu c2/c3 có đúng một canary `ACME-CANARY-<DEPT>-<nnnn>`; `allowed_roles` trên một số tài liệu c2 và
  toàn bộ c3 của HR. Corpus markdown ở `generated/corpus/<DEPT>/*.md`; **không embed** — ingest/embedding là việc
  của docs-mcp (`chunks` để trống).
- **Ticket:** 100 ticket (`assignee_dept` SALES 55 / HR 45; open 20, in_progress 25, resolved 25, closed 30),
  khoảng 170 bình luận (25% internal), sự kiện `create/status/close`; ~15% mô tả có PII giả
  (danh sách trong `manifest.json`).
- **Analytics:** 40 khách hàng (10% thuộc CS), 12 sản phẩm, 300 đơn, ~735 dòng đơn, 3 đơn bất thường (x20).
- **Gateway:** bảng `departments` (SALES, ENG, HR, CS, IT, EVAL). Không seed `api_keys` (cần `GW_KEY_PEPPER`;
  tạo bằng lệnh admin của gateway).
- **User:** đọc `infra/keycloak/realm-acme.json` (16 user). Realm cố định `id` mỗi user (uuid5 theo
  username) nên `requester_sub` khớp `sub` của JWT thật. Keycloak đã import realm từ trước bản có `id`
  thì xoá volume Keycloak để import lại, hoặc dùng `--sub-map map.json` (`{"an.nguyen": "<uuid>", ...}`).
