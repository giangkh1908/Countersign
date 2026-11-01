# ADR-007: Mở lại hành động qua MCP, phân quyền theo vai trò, cache và quan sát

- Trạng thái: Đã chấp nhận (2026-11-01)
- Sửa đổi: [ADR-006](ADR-006-scope-rag-citations.md). ADR-006 vẫn hiệu lực cho RQ1, RQ2, corpus và cách đánh giá; phần đóng băng/bỏ dưới đây được thay bằng ADR này.

## Bối cảnh

ADR-006 thu hẹp đề tài về hỏi đáp có trích dẫn và đóng băng ticket, quan sát, cache. User muốn trợ lý làm được việc chứ không chỉ trả lời: tạo ticket, báo cáo vào nhóm chat qua MCP, phân quyền theo vai trò, có cache, log, trace, eval.

Hiện trạng (kiểm trong code 2026-11-01):

| Hạng mục | Đã có | Chưa có |
|---|---|---|
| Ticket | `list_my_tickets`, `get_ticket`, `search_tickets`, `prepare_close_ticket` + phê duyệt ký số | Tạo ticket |
| Báo cáo nhóm | Không | Toàn bộ |
| Vai trò | 6 realm role (`employee`, `team_lead`, `dept_manager`, `management`, `admin`, `auditor`); `allowed_roles` + RLS trên tài liệu | Ma trận quyền theo tool và theo kênh |
| Cache | Port `ResponseCache`, adapter `redis_exact`, `redis_semantic`, `null_cache` | Khoá theo phạm vi quyền, số đo |
| Trace | Biến `OTEL_EXPORTER_OTLP_ENDPOINT` | Instrument trong service |
| Metric, log | Prometheus + Grafana (profile `obs`), log có cấu trúc, hash-chain audit | Dashboard RAG/cache, gom log |

## Quyết định

Đề tài: **trợ lý AI nội bộ trả lời từ tài liệu có trích dẫn kiểm chứng được, thực hiện việc qua MCP, phân quyền theo vai trò, có cache và quan sát đầy đủ.** Trích dẫn vẫn là phần nghiên cứu chính.

Câu hỏi nghiên cứu: giữ RQ1, RQ2. Sửa và thêm:
- **RQ3 An toàn (mở rộng):** ngoài rò tài liệu trái quyền, đo tài liệu độc có lừa được agent tạo ticket hoặc gửi dữ liệu mật vào nhóm chat không.
- **RQ4 Cache (mới):** cache tiết kiệm bao nhiêu chi phí và độ trễ, có làm giảm chất lượng trả lời hay rò dữ liệu giữa các phạm vi quyền không.

### Hành động qua MCP

- Bật lại `tickets-mcp`, thêm `prepare_create_ticket`. Mọi thao tác ghi đi qua luồng intent + phê duyệt ký số đã có; không mở đường ghi thứ hai.
- MCP server mới `notify-mcp`, tool `prepare_send_group_report`, cũng qua phê duyệt. Port `MessageChannel`, mỗi kênh một adapter (`telegram`, `slack`, `zalo_oa`, `fake`), chọn bằng registry trong `factory.py`.
- Làm **Telegram trước**. Slack và Zalo OA chỉ là thêm adapter, không sửa code nghiệp vụ.
- Agent chỉ chọn **bí danh kênh** khai báo sẵn ở server, không truyền chat ID tuỳ ý. Bot token chỉ nằm ở `notify-mcp`, đọc từ secret file.
- Mỗi kênh có mức mật tối đa. Báo cáo chứa dữ liệu cao hơn mức của kênh thì bị chặn ở server, dùng lại cơ chế taint/classification.

### Phân quyền theo vai trò

Thực thi ở phía server: RLS cho dữ liệu, `AuthMiddleware` của MCP cho tool. Agent ẩn tool chỉ để tiện dùng, không phải lớp bảo vệ.

Dự thảo ma trận, chốt ở milestone A1:

| Vai trò | Tạo ticket | Đóng ticket | Gửi nhóm phòng | Gửi nhóm toàn công ty |
|---|---|---|---|---|
| `employee` | Có | Ticket được giao | Không | Không |
| `team_lead` | Có | Ticket được giao | Có | Không |
| `dept_manager` | Có | Trong phòng | Có | Không |
| `management` | Có | Trong phòng | Có | Có |
| `admin` | Không | Không | Không | Không |
| `auditor` | Không | Không | Không | Không |

`admin` quản trị cấu hình, `auditor` chỉ đọc audit; cả hai không dùng trợ lý để ghi nghiệp vụ.

### Cache

- Bật **exact cache** trước, khoá gồm model, nội dung prompt và phạm vi quyền (phòng ban, cấp mật, vai trò).
- Semantic cache chỉ là thử nghiệm trong RQ4, mặc định tắt. Hai câu "gần giống nhau" của hai người khác quyền là nguồn rò rỉ, nên phải có số đo mới được bật.
- Không cache câu trả lời có thao tác ghi. Câu trả lời cache vẫn phải giữ nguyên trích dẫn đã kiểm chứng.

### Quan sát

- Trace bằng OpenTelemetry xuyên BFF → agent → gateway → MCP, truyền `traceparent`. OTel là chuẩn mở nên không bọc port.
- Log JSON hiện có, thêm `trace_id`. Metric qua Prometheus + Grafana.
- Backend trace chọn một loại nhẹ, chạy ở profile `obs`; chốt khi làm milestone Q1. Langfuse chỉ thêm nếu backend đó không đủ.
- Trace và log **không chứa nội dung** prompt, tài liệu, câu trả lời. Quét canary phải bao phủ cả trace.

### Eval

Thêm eval hành động: chọn đúng tool, đúng tham số, từ chối đúng khi thiếu quyền, không hành động khi người dùng chỉ hỏi. Toàn bộ eval vẫn theo nguyên tắc chạy lại được bằng một lệnh.

### Vẫn giữ nguyên quyết định của ADR-006

Bỏ: trang admin, i18n, HA, mTLS, Helm, secret manager, router chi phí, rate limit và budget đầy đủ, fallback nhiều provider.
Đóng băng: `analytics-mcp`, `policy-sidecar`.

## Tự xây hay dùng lại

Khảo sát GitHub ([`research/06-github-survey.md`](../research/06-github-survey.md)): không thấy dự án mở nào có đủ tổ hợp này, nên giữ hướng tự xây lõi.
- `notify-mcp` tự viết, adapter Telegram dùng Bot API. MCP Telegram phổ biến nhất chạy bằng tài khoản người dùng, và các MCP nhắn tin có sẵn không có bí danh kênh, mức mật, phê duyệt.
- Quan sát: thử OpenLLMetry (OTel) trước khi cân nhắc Langfuse.
- Eval: metric tự viết là chính; DeepEval/Ragas chạy đối chứng.

## Hệ quả

- Thứ tự: R0 → R1 → R2 → A1 (hành động, vai trò) → Q1 (cache, quan sát) → R3 (an toàn) → R4 (tổng hợp). R3 đứng sau A1 vì phải có hành động thật mới đo được tấn công qua hành động.
- Compose mặc định vẫn gọn cho hỏi đáp, mục tiêu dưới 2,5 GB lúc rảnh trên VPS 4 GB giữ nguyên **cho stack mặc định**. Bật `tickets`, `notify`, `obs` sẽ vượt mức này; A1 và Q1 phải đo RAM thật, chưa đặt mục tiêu khi chưa có số.
- Gửi tin ra ngoài là thao tác không thu hồi được, nên test và eval dùng adapter `fake`; chỉ demo mới dùng bot thật trong nhóm thử nghiệm.
- Rủi ro lớn nhất là dàn mỏng lần nữa. Nếu thiếu thời gian, cắt theo thứ tự: Slack/Zalo OA → semantic cache → gom log.
