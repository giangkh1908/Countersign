# eval/

Hiện có hai E2E trên stack compose thật: `e2e/close_ticket.py` (profile `tickets`, `bash scripts/e2e-close-ticket.sh`) và `e2e/notify.py` (profile `tickets` + `notify`, `bash scripts/e2e-notify.sh`; dùng lại hạ tầng của close_ticket). Trong worktree không có `secrets/`, đặt `SECRETS_DIR` trỏ tới thư mục secrets của repo chính.

Bộ đánh giá RAG (truy xuất, trích dẫn, an toàn, ablation) chưa có; thêm thư mục khi làm R1–R4 ([`ROADMAP`](../docs/ROADMAP.md)). Số liệu phải tái lập được bằng một lệnh, ghi seed, phiên bản model, prompt và chi phí.
