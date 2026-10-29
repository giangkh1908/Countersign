# data/ — dữ liệu giả lập "ACME Việt Nam"

Thiết kế: `docs/design/04-infra-data-eval.md` PHẦN B (§7–§8). Mọi PII là giả.

| Thư mục | Nội dung |
|---|---|
| `generator/` | Generator ACME có seed (`20261028`): tài liệu (~200), ticket (~2.000), analytics, người dùng. Stub, chưa có logic |
| `corpus/` | Corpus độc cho E4 (>= 50 tài liệu, 8 kỹ thuật injection, có ground truth) |
| `pii_testset/` | Tập test PII viết tay (tập chính cho bộ lọc PII, R11/R13) |
| `seed/` | Dữ liệu seed nạp vào Postgres |
| `generated/` | Đầu ra của generator, đã gitignore |
