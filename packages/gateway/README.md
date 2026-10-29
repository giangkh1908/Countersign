# gateway

LLM Gateway: OpenAI-compatible `/v1`, pipeline stage (auth, ratelimit, budget, pii, guard, cache, router), audit/usage. Service duy nhất có egress và giữ khóa provider. Không nạp model nặng; gọi `policy-sidecar` qua HTTP.

- Cổng: 8000 (host 8000 dev)
- Mạng docker: `core` + `egress`
- Tài liệu: `docs/design/01-gateway.md`, `docs/design/00-contracts.md` §1, §7, §9.2
