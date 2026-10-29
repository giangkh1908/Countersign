# Research 01 — Sự cố LiteLLM 2026, so sánh gateway, giá API (reader/Haiku, 2026-10-28)

> Nguồn bậc 2 (báo chí/blog bảo mật) được đánh dấu. Cần đối chiếu lại nguồn gốc trước khi trích dẫn trong báo cáo đồ án.

## 1. Sự cố LiteLLM 2026
- **10/2026 — v1.107.0 bị cài mã độc (PyPI + Docker)** [nguồn bậc 2]: wheel chứa `cook.pth`, `cook.py`, `sitecustomize.py`. Các file này chạy ngay khi Python khởi động. Payload đánh cắp credential (cloud, git, SSH, `.env`, env vars, tối đa 500 dòng từ 2 bảng DB của proxy), mã hoá AES-256+RSA rồi exfiltrate. Nguyên nhân: credential GitHub bị đánh cắp → workflow release bị trỏ sang repo giả `Berri-AI/litellm` → dùng credential của dev khác để vượt bước approve. Khắc phục: rebuild từ artifact sạch, pin image theo digest, xoay toàn bộ credential.
  - https://www.microsoft.com/en-us/security/blog/2026/10/23/inside-the-litellm-1-107-0-supply-chain-compromise-credential-theft-through-python-startup-hooks/
  - https://thehackernews.com/2026/10/litellm-compromised-in-supply-chain.html
  - https://www.helpnetsecurity.com/2026/10/22/litellm-compromised-supply-chain-attack-pypi-docker/
- **03/2026 — v1.82.7 / 1.82.8** [nguồn bậc 2]: nhóm TeamPCP chiếm credential publish PyPI sau khi Trivy bị xâm phạm. CloudSEK ước tính ~2.500 tổ chức bị ảnh hưởng (chưa kiểm chứng độc lập).
  - https://www.securityweek.com/over-2500-organizations-impacted-by-litellm-supply-chain-attack/
  - https://www.zscaler.com/blogs/security-research/supply-chain-attacks-surge-march-2026
- **CVE-2026-42208 — SQLi pre-auth** [GHSA/OSV]: giá trị header Authorization bị ghép thẳng vào câu SQL kiểm tra key. Ảnh hưởng 1.81.16 đến trước 1.83.7. CVSS 9.3 (v4) / 9.8 (v3). Có báo cáo nằm trong CISA KEV 2026-05-08 (chưa xác minh với CISA).
  - https://osv.dev/vulnerability/GHSA-r75f-5x8p-qvmc
- CVE khác: CVE-2026-42271 (9.8, thực thi lệnh qua MCP stdio test endpoint), CVE-2026-59819 (8.8, đọc file qua OIDC), CVE-2024-5751 (9.8, RCE `/config/update`), CVE-2024-6587 (SSRF qua `api_base`, lộ key), CVE-2024-4888 (xoá file tuỳ ý), CVE-2025-11203 (lộ key qua health endpoint), CVE-2025-45809 (SQLi `/key/block`).
  - https://notcve.org/vendors/litellm/ , https://www.cvelogic.com/vendor/litellm

**Bài học cho đồ án:** (a) rủi ro supply chain → ít dependency, pin hash (`uv.lock` + `--require-hashes`), image theo digest; (b) truy vấn tham số hoá, key lưu dạng hash; (c) bề mặt tấn công nhỏ, không có endpoint admin "tiện lợi" (config update, MCP stdio test, SSRF qua `api_base`).

## 2. So sánh gateway
| Gateway | License | Tính năng | Overhead công bố |
|---|---|---|---|
| LiteLLM proxy | OSS (+ enterprise) | virtual key, budget, rate limit, fallback, nhiều CVE 2024–2026 | chưa có số liệu |
| Portkey gateway | MIT (enterprise riêng) | 200+ LLM, fallback, retry, cache, guardrails | vendor tự công bố 20–40 ms; benchmark bên thứ ba ~851 req/s @150 VU |
| Kong AI Gateway | một phần OSS (plugin Kong) | semantic cache/routing, rate limit theo token | chưa có |
| Envoy AI Gateway | Apache-2.0 (chưa xác minh) | dựa trên Envoy/K8s | chưa có |
| Cloudflare AI Gateway | managed, không self-host | cache, logging | chưa có |

Nguồn: https://github.com/portkey-ai/gateway , https://dev.to/ferrolabs-ai/ai-gateways-are-not-io-bound-proxies-i-benchmarked-5-of-them-to-prove-it-4iji (đối thủ cạnh tranh viết). Hầu hết không công bố p50/p99 → **đây là khoảng trống mà phần benchmark của đồ án có thể lấp**.

## 3. Thực hành tự xây gateway (SUY LUẬN, chưa có nguồn)
Lưu key dạng HMAC-SHA256 + pepper. SSE passthrough, đếm token từ `usage` ở chunk cuối (OpenAI `stream_options.include_usage`). Circuit breaker có half-open. Bảng giá có ngày hiệu lực. Token bucket Redis + Lua (atomic).

## 4. Giá API (USD / 1M token, input/output) — fetch 2026-10-28
- Claude (https://claude.com/pricing): **Haiku 5.5 $0.10/$0.50** (≤100K prompt), **Sonnet 5.5 $2/$10**, Opus 5.5 $4/$20. Batch −50%.
- Gemini (https://ai.google.dev/gemini-api/docs/pricing, cập nhật 2026-10-27): **2.5 Flash-Lite $0.10/$0.40**, 3.1 Flash-Lite $0.25/$1.50, 2.5 Flash $0.30/$2.50, 3.8 Flash $0.75/$3.75 (gấp đôi từ 1/1/2027), 3.1 Pro Preview $2/$12.
- Giá thay đổi nhanh → lưu trong `pricing.yaml` có `effective_from`.
