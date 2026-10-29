# Trên Windows: chạy trong Git Bash hoặc WSL (Makefile dùng bash).
SHELL := bash
.PHONY: setup lint fmt test test-web leak-grep secrets up down logs bench eval backup clean

setup:
	uv sync
	cd web && pnpm install

lint:
	uv run ruff format --check .
	uv run ruff check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest

test-web:
	cd web && pnpm test

leak-grep:
	bash scripts/leak-grep.sh

secrets:
	bash infra/scripts/gen-secrets.sh

up:
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

bench:
	docker compose -f docker-compose.yml -f docker-compose.bench.yml --profile bench up -d --wait
	@echo "TODO(M5): chạy eval/bench (k6/vegeta)"

eval:
	uv run pytest eval -m "not live"

backup:
	bash infra/scripts/backup.sh

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache web/node_modules web/dist
