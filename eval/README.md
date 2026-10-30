# eval/ — bộ đánh giá

Phạm vi theo [ADR-006](../docs/adr/ADR-006-scope-rag-citations.md) và [ROADMAP](../docs/ROADMAP.md) R1–R4. Chạy riêng, không nằm trong `uv run pytest` ở root (testpaths = `packages`): `make eval` (= `uv run pytest eval -m "not live"`).

## Đang có

- `security/` — security regression (pytest), `check_pth.sh` kiểm `.pth`/`sitecustomize` trong venv
- `e2e/` — `close_ticket.py` (E2E đóng ticket, luồng đóng băng; chạy qua `scripts/e2e-close-ticket.sh`)
- `bench/`, `promptfoo/`, `notebooks/` — khung/placeholder từ lộ trình cũ, chưa dùng cho đề tài mới

## Cấu trúc đánh giá mới (dự kiến, chưa có)

| Thư mục | Milestone | Nội dung |
|---|---|---|
| `retrieval/` (dự kiến) | R1 | Bộ ~150 câu hỏi có nhãn vàng (văn bản, Điều, khoản); script tính recall@k, MRR, nDCG theo loại câu; so 4 cấu hình: vector, BM25, hybrid, hybrid+rerank. Phụ: chạy cùng script trên Zalo legal làm benchmark ngoài |
| `citations/` (dự kiến) | R2 | Citation precision/recall, faithfulness, tỉ lệ từ chối đúng với câu không có đáp án; có và không có bộ kiểm chứng; chi phí/câu, độ trễ p50/p95; hiệu chuẩn judge (Cohen's κ) |
| `safety/` (dự kiến) | R3 | Kiểm rò rỉ trái quyền theo 16 user (câu trả lời, trích dẫn, cache, log, canary); ASR của corpus độc `data/corpus/` theo kỹ thuật injection, có/không spotlighting và bộ kiểm chứng. Hồi quy chạy trong CI |
| `ablation/` (dự kiến) | R4 | Bỏ từng thành phần (hybrid, rerank, kiểm chứng, spotlighting) và so chất lượng, an toàn, chi phí; chạy với ≥ 2 model |

Yêu cầu chung: mọi số liệu tái lập được bằng một lệnh, ghi seed, phiên bản model/prompt và chi phí.
