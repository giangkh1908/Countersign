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
# check_pth.sh (liệt kê .pth/sitecustomize lạ, fail nếu ngoài allowlist) do worker khác tạo.
COPY eval/security/check_pth.sh ./eval/security/check_pth.sh

# ───────────── gateway (8000) ─────────────
FROM base AS gateway
RUN uv sync --frozen --no-dev --package acme-gateway
RUN bash eval/security/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]

# ───────────── policy-sidecar (8010) ─────────────
FROM base AS policy_sidecar
# onnxruntime/tokenizers/underthesea CHỈ ở target này
RUN uv sync --frozen --no-dev --package acme-policy-sidecar
RUN bash eval/security/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
# models KHÔNG nằm trong image (mount read-only, verify theo models.lock); image không chứa token HF
CMD ["uvicorn", "policy_sidecar.main:app", "--host", "0.0.0.0", "--port", "8010", "--no-server-header"]

# ───────────── approval-signer (8310) ─────────────
FROM base AS approval_signer
# chỉ fastapi + pyjwt + cryptography
RUN uv sync --frozen --no-dev --package acme-approval-signer
RUN bash eval/security/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "approval_signer.main:app", "--host", "0.0.0.0", "--port", "8310", "--no-server-header"]

# ───────────── mock-provider (8900) ─────────────
FROM base AS mock_provider
RUN uv sync --frozen --no-dev --package acme-mock-provider
RUN bash eval/security/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "mock_provider.main:app", "--host", "0.0.0.0", "--port", "8900", "--no-server-header"]

# ───────────── MCP servers (8101/8102/8103) ─────────────
FROM base AS mcp_docs
RUN uv sync --frozen --no-dev --package acme-mcp-docs
RUN bash eval/security/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "mcp_docs.main:app", "--host", "0.0.0.0", "--port", "8101", "--no-server-header"]

FROM base AS mcp_tickets
RUN uv sync --frozen --no-dev --package acme-mcp-tickets
RUN bash eval/security/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "mcp_tickets.main:app", "--host", "0.0.0.0", "--port", "8102", "--no-server-header"]

FROM base AS mcp_analytics
RUN uv sync --frozen --no-dev --package acme-mcp-analytics
RUN bash eval/security/check_pth.sh /app/.venv
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "mcp_analytics.main:app", "--host", "0.0.0.0", "--port", "8103", "--no-server-header"]

# ───────────── agent (8200) ─────────────
FROM base AS agent
RUN uv sync --frozen --no-dev --package acme-agent
RUN bash eval/security/check_pth.sh /app/.venv
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
RUN uv sync --frozen --no-dev --package acme-bff
RUN bash eval/security/check_pth.sh /app/.venv
# BFF phục vụ SPA cùng origin
COPY --from=web_build /web/dist /app/static
USER 10001
ENV PATH="/app/.venv/bin:$PATH" BFF_STATIC_DIR=/app/static
CMD ["uvicorn", "bff.main:app", "--host", "0.0.0.0", "--port", "8300", "--no-server-header"]

# ───────────── job một lần: migrate / seed ─────────────
# TODO(M1): migrate = Alembic bằng các role *_owner (entrypoint dựng URL từ secret *_owner_password).
FROM base AS migrate
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "echo 'TODO: migrate placeholder (Alembic chưa có)'"]

# TODO(M1): seed = generator dữ liệu mẫu (docs/design/04 §7).
FROM base AS seed
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "echo 'TODO: seed placeholder (generator chưa có)'"]
