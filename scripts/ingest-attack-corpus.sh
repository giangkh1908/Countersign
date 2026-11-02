#!/usr/bin/env bash
# Nạp corpus độc (data/corpus) vào kho tri thức bằng pipeline ingest sẵn có (cờ --corpus-dir).
# CHỈ chạy khi chủ đích đo ASR tầng LLM trên stack: corpus có chỉ thị lừa agent nên không nạp vào kho dùng thật.
# Cần stack đang chạy và cấu hình DB/embedder trong .env như ingest thường. Thêm --force để nạp lại.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run --all-packages python -m data.poison --out data/corpus >/dev/null  # đảm bảo corpus khớp generator
exec uv run --all-packages python -m mcp_docs.ingest --corpus-dir data/corpus "$@"
