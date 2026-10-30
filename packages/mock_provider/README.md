# mock-provider

Giả lập API OpenAI/Anthropic/Gemini cho dev, test, bench. Có `/__control` (chaos).

- Cổng: 8900 (không expose host)
- Mạng docker: `core`
- Tài liệu: `docs/design/00-contracts.md` §1; `docs/design/04-infra-data-eval.md`

## Endpoint
- `POST /v1/messages`, `POST /v1/chat/completions`, `POST /v1beta/models/{model}:generateContent|:streamGenerateContent?alt=sse`
- `GET /healthz`; `GET /metrics` (Bearer `METRICS_TOKEN`); `GET|PUT /__control[/{scope}]`, `DELETE /__control` (Bearer `MOCK_CONTROL_TOKEN[_FILE]` nếu có)

## Hành vi
Ưu tiên: header `x-mock-<tên>` > `/__control` (scope wire, rồi `*`) > env `MOCK_*`.
Tên: `ttft_ms`, `token_delay_ms`, `output_tokens`, `error_rate`, `error` (`429|500|503|timeout|stream_cut|none`), `error_kinds`, `retry_after_s`, `hang_s`, `seed`.
Prompt `echo: <text>` trả lại đúng text; `call_tool:<tên> {json}` + request có tools trả tool call. `MOCK_REQUIRED_KEY` đặt thì key sai -> 401.
Token = từ hoặc dấu câu (`behavior.count_tokens`); usage output luôn bằng số delta stream.
