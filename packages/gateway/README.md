# gateway

LLM Gateway: OpenAI-compatible `/v1`, pipeline stage (auth, ratelimit, budget, pii, guard, cache, router), audit/usage. Service duy nhất có egress và giữ khóa provider. Không nạp model nặng; gọi `policy-sidecar` qua HTTP.

- Cổng: 8000 (host 8000 dev)
- Mạng docker: `core` + `egress`
- Tài liệu: `docs/design/01-gateway.md`, `docs/design/00-contracts.md` §1, §7, §9.2

## M1 (gateway mỏng)

- `POST /v1/chat/completions` (OpenAI-compatible: non-stream, SSE, tool calling), `/healthz`, `/metrics` (Bearer `METRICS_TOKEN`).
- Alias model: `config/models.yaml` (gateway tìm `./config/models.yaml`, hoặc `GW_MODELS_CONFIG`). Image Docker cần COPY thư mục `packages/gateway/config` thành `/app/config`.
- Tạo/thu hồi API key (cần `GW_DATABASE_URL`, `GW_KEY_PEPPER`; cả hai hỗ trợ `_FILE`):

  ```
  uv run python -m gateway.cli create-key --name agent --dept IT --allowed-models acme-fast,acme-smart,acme-auto --trust-end-user-token
  uv run python -m gateway.cli revoke-key --key-id <uuid> --reason "..."
  ```
- Dev không cần provider thật: `GW_PROVIDER_OVERRIDE=mock GW_MOCK_BASE_URL=http://mock-provider:8900`.
- Test Postgres thật: đặt `TEST_DATABASE_URL` (DB đã áp `30-gateway.sql`, có phòng `IT` hoặc `TEST_GW_DEPT`); không đặt thì skip.
- Chưa có (M2): rate limit, budget, cache, PII, guard, fallback, breaker, retry, Redis L2 của KeyStore, giá (`cost_micro_usd` = 0).
