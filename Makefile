# Trên Windows: chạy trong Git Bash hoặc WSL (Makefile dùng bash).
SHELL := bash
.PHONY: eval-attack setup lint fmt test test-web leak-grep eval-rag eval-rag-fake eval-rag-validate secrets up down logs backup clean

setup:
	uv sync --all-packages
	cd web && pnpm install

lint:
	uv run ruff format --check .
	uv run ruff check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run --all-packages pytest -q

test-web:
	cd web && pnpm test

leak-grep:
	bash scripts/leak-grep.sh

# Đánh giá truy xuất (R1). Cần corpus thô: data/raw/vbpl hoặc VBPL_RAW_DIR=<thư mục>.
eval-rag-validate:
	uv run --all-packages python -m eval.rag validate --suite vbpl-v1

eval-rag-fake:
	uv run --all-packages python -m eval.rag run --suite vbpl-v1 --fake

eval-rag:
	uv run --all-packages python -m eval.rag run --suite vbpl-v1

secrets:
	bash scripts/gen-secrets.sh

up:
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

backup:
	bash scripts/backup.sh

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache web/node_modules web/dist

# ASR tầng hệ thống (R3), trong-process, không cần stack. Corpus: data/corpus (sinh bằng python -m data.poison).
eval-attack:
	uv run --all-packages python -m eval.attack --check
