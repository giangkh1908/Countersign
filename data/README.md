# data/ — dữ liệu "ACME Việt Nam" và corpus luật

Mọi PII là giả. Nguồn và giấy phép corpus luật: [`SOURCES.md`](SOURCES.md).

| Thư mục | Nội dung |
|---|---|
| `generator/` | Generator ACME có seed (`20261028`), stdlib, không gọi LLM: 30 tài liệu, 100 ticket, SQL seed, user lấy từ realm |
| `tests/` | Test offline của generator (`uv run pytest data/tests`) |
| `load_seed.sh` | Nạp SQL seed vào Postgres trong compose (idempotent) |
| `vbpl/` | Tải corpus luật từ vbpl.vn; danh sách chọn `selection.json` |
| `generated/`, `raw/` | Đầu ra generator và dữ liệu tải về, gitignore |

Corpus độc cho R3 chưa có; thư mục sẽ được tạo khi làm.

## Chạy seed

```
uv run python -m data.generator        # -> data/generated/ (xoá và ghi lại toàn bộ)
bash data/load_seed.sh                 # nạp gateway, knowledge, tickets
bash infra/postgres/verify/run.sh      # kiểm RLS và quyền trên DB thật
```

Tuỳ chọn generator: `--seed N`, `--out DIR`, `--realm FILE`, `--sub-map FILE`. Cùng seed thì đầu ra giống từng byte (`manifest.json` có sha256). Seed chạy bằng superuser `postgres` nên bỏ qua RLS ở bước nạp. Ingest vào kho tri thức: xem README gốc.

## Nội dung seed

- Tài liệu: 30 (c0=5, c1=11, c2=8, c3=6) ở phòng `ALL`, `SALES`, `HR`; mỗi tài liệu c2/c3 có một canary `ACME-CANARY-<DEPT>-<nnnn>`. Markdown ở `generated/corpus/<DEPT>/*.md`.
- Ticket: 100 ticket kèm bình luận và sự kiện; khoảng 15% mô tả có PII giả.
- Gateway: bảng `departments` (SALES, ENG, HR, CS, IT, EVAL). Không seed `api_keys`; tạo bằng `scripts/bootstrap-gateway-keys.sh`.
- User: đọc `infra/keycloak/realm-acme.json` (16 user, `id` cố định theo uuid5 của username nên `requester_sub` khớp `sub` của JWT). Keycloak đã import realm cũ thì xoá volume Keycloak, hoặc dùng `--sub-map map.json`.
