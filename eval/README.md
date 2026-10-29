# eval/ — bộ đánh giá (M5)

Thiết kế: `docs/design/04-infra-data-eval.md` PHẦN C.

- `bench/` — benchmark tải (k6/vegeta), E1–E3
- `promptfoo/` — đánh giá chất lượng/red-team bằng promptfoo
- `security/` — security regression (pytest), `check_pth.sh` kiểm `.pth`/`sitecustomize` trong venv
- `notebooks/` — notebook phân tích kết quả

Chạy riêng, không nằm trong `uv run pytest` ở root (testpaths = `packages`):
`uv run pytest eval/security/tests` hoặc `make eval`.
