# syntax=docker/dockerfile:1.7
# Dockerfile đa tầng dùng chung cho mọi service Python (chọn bằng `target`).
# Nguồn: docs/design/04-infra-data-eval.md §1.5. Build context = gốc repo.
# Cần: pyproject.toml (uv workspace) + uv.lock + packages/<svc> (tạo bởi worker khác).

# TODO(M7): pin digest cho mọi image gốc (python, uv, node) bằng `make pin-digests`.
FROM python:3.12-slim AS base
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# TODO(M7): pin digest
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
# check_pth.sh: liệt kê .pth/sitecustomize lạ, fail nếu ngoài allowlist (pth-allowlist.txt cùng thư mục).
COPY scripts/check_pth.sh scripts/pth-allowlist.txt ./scripts/

# ───────────── gateway (8000) ─────────────
FROM base AS gateway
RUN uv sync --frozen --no-dev --no-editable --package acme-gateway
RUN bash scripts/check_pth.sh /app/.venv
# named volume audit_anchors kế thừa chủ sở hữu thư mục này khi khởi tạo lần đầu
RUN mkdir /anchors && chown 10001 /anchors
USER 10001
ENV PATH="/app/.venv/bin:$PATH" \
    GW_MODELS_CONFIG=/app/packages/gateway/config/models.yaml
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]

# ───────────── approval-signer (8310) ─────────────
FROM base AS approval_signer
# chỉ fastapi + pyjwt + cryptography
RUN uv sync --frozen --no-dev --no-editable --package acme-approval-signer
RUN bash scripts/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "approval_signer.main:app", "--host", "0.0.0.0", "--port", "8310", "--no-server-header"]

# ───────────── mock-provider (8900) ─────────────
FROM base AS mock_provider
RUN uv sync --frozen --no-dev --no-editable --package acme-mock-provider
RUN bash scripts/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "mock_provider.main:app", "--host", "0.0.0.0", "--port", "8900", "--no-server-header"]

# ───────────── MCP servers (8101/8102) ─────────────
FROM base AS mcp_docs
RUN uv sync --frozen --no-dev --no-editable --package acme-mcp-docs
RUN bash scripts/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "mcp_docs.main:app", "--host", "0.0.0.0", "--port", "8101", "--no-server-header"]

FROM base AS mcp_tickets
RUN uv sync --frozen --no-dev --no-editable --package acme-mcp-tickets
RUN bash scripts/check_pth.sh /app/.venv
# named volume audit_anchors kế thừa chủ sở hữu thư mục này khi khởi tạo lần đầu
RUN mkdir /anchors && chown 10001 /anchors
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "mcp_tickets.main:app", "--host", "0.0.0.0", "--port", "8102", "--no-server-header"]

# ───────────── agent (8200) ─────────────
FROM base AS agent
RUN uv sync --frozen --no-dev --no-editable --package acme-agent
RUN bash scripts/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8200", "--no-server-header"]

# ───────────── bff (8300) — D15: node chỉ ở stage build ─────────────
# TODO(M7): pin digest
FROM node:22-slim AS web_build
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
# -> /web/dist (CSP không cho script inline)
RUN pnpm build

FROM base AS bff
RUN uv sync --frozen --no-dev --no-editable --package acme-bff
RUN bash scripts/check_pth.sh /app/.venv
# BFF phục vụ SPA cùng origin
COPY --from=web_build /web/dist /app/static
USER 10001
ENV PATH="/app/.venv/bin:$PATH" BFF_STATIC_DIR=/app/static
CMD ["uvicorn", "bff.main:app", "--host", "0.0.0.0", "--port", "8300", "--no-server-header"]

# ───────────── job một lần: migrate / seed ─────────────
# migrate: hiện chỉ tạo schema checkpointer LangGraph của agent (`python -m agent.migrate`, role ag_owner).
# TODO(M1): Alembic cho các DB khác (hiện bảng nghiệp vụ do infra/postgres/init/sql tạo).
FROM base AS migrate
RUN uv sync --frozen --no-dev --no-editable --package acme-agent
RUN bash scripts/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "agent.migrate"]

# TODO(M1): seed = generator dữ liệu mẫu (docs/design/04 §7).
FROM base AS seed
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "echo 'TODO: seed placeholder (generator chưa có)'"]
