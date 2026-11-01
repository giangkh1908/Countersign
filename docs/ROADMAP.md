# Lộ trình (v2.1): Trợ lý AI nội bộ có trích dẫn kiểm chứng được và hành động qua MCP

> Phiên bản 2.1, 2026-11-01. Phạm vi theo [ADR-006](adr/ADR-006-scope-rag-citations.md) và [ADR-007](adr/ADR-007-actions-cache-observability.md). Lộ trình v1.3 (gateway đầy đủ, analytics, admin, hardening) xem lịch sử git.
> Mỗi milestone kết thúc bằng bản chạy được, test xanh, đạt DoD đo được. Ký hiệu: **R** = reader, **W** = worker, **O** = orchestrator.
> Quy tắc vận hành: mỗi lúc một worker, phạm vi hẹp; review và merge xong mới giao việc tiếp; backup trước mọi thay đổi trạng thái.

## Tổng quan

| Milestone | Chủ đề | Trạng thái |
|---|---|---|
| M0 | Spikes (identity, token exchange, checkpoint) | Xong |
| M1 | Walking skeleton trên compose | Gần xong (còn README) |
| R0 | Thu gọn stack | |
| R1 | Truy xuất thật + bộ đánh giá truy xuất | |
| R2 | Câu trả lời có trích dẫn kiểm chứng được | |
| A1 | Hành động qua MCP: ticket, báo cáo nhóm, phân quyền theo vai trò | |
| Q1 | Cache và quan sát (log, trace, metric) | |
| R3 | An toàn: phân quyền, tài liệu độc, tấn công qua hành động | |
| R4 | Đánh giá tổng hợp, demo, báo cáo | |

## M1 — Walking skeleton (đã đạt phần lớn)

Đã có:
- compose khoẻ, `scripts/smoke.sh`;
- gateway ghi `usage_events`;
- E2E đóng ticket 56/56 trên stack thật (luồng này nay đóng băng, profile `tickets`);
- Playwright: đăng nhập thật qua BFF, chat mock, khẳng định không có token trong trình duyệt.

Còn lại:
- README chạy từ máy sạch ≤ 15 phút.

## R0 — Thu gọn stack

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| ✅ (345f304) Đưa tickets-mcp + approval-signer vào profile `tickets`; agent chạy được khi không có ticket (router chỉ docs/direct) | W | `docker compose up` mặc định không có 2 service này; smoke xanh; `--profile tickets` + E2E đóng ticket vẫn xanh |
| Gỡ `depends_on` của agent → tickets-mcp và bff → approval-signer; gateway mặc định `GW_FEATURES=auth` (+ ghi usage), bỏ `GW_SIDECAR_URL` khỏi mặc định | W | Stack mặc định khoẻ khi không có tickets/sidecar |
| Đo RAM/CPU lúc rảnh và khi chạy 20 câu hỏi; ghi bảng vào README | W | Bảng số đo thật; mục tiêu < 2,5 GB lúc rảnh |
| Tắt `directAccessGrants` của client `admin-cli` trong realm `acme` | W | Test realm: không client nào cho password grant |
| Cập nhật CLAUDE.md, SOLUTION theo ADR-006 | O | Xong (2026-10-30) |

**DoD R0:** compose mặc định chỉ gồm postgres, redis, keycloak, gateway, mock-provider, docs-mcp, agent, bff; smoke xanh; profile `tickets` vẫn xanh; bảng tài nguyên trong README.

## R1 — Truy xuất thật + bộ đánh giá truy xuất

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Gateway `/v1/embeddings` (OpenAI-compatible), alias `acme-embed`, port `EmbeddingProvider`, adapter provider thật + mock tất định; ghi `usage_events` | W | Test hợp đồng bằng SDK `openai`; leak-grep rỗng |
| Chọn model embedding; migration `chunks` theo đúng số chiều (bỏ cứng `vector(1024)`), thêm cột `article`, `clause`, `char_start`, `char_end` | W | Migration lên/xuống được; kiểm số chiều khi khởi động |
| docs-mcp: loader `vbpl_articles` (JSON Điều từ `data/vbpl`, cắt Điều dài theo khoản), gán `department`/`classification` theo nhóm như `data/SOURCES.md` | W | 19 văn bản / 1.557 Điều nạp đủ; nạp lại ra cùng số chunk |
| docs-mcp: embedder thật qua gateway (bỏ `fake_hash` khỏi đường mặc định); ingest corpus luật + 30 tài liệu ACME tổng hợp | W | Ingest lặp lại được; số chunk khớp |
| Bộ câu hỏi có nhãn ~150 câu trên corpus luật: LLM sinh nháp từ từng Điều, người kiểm; nhãn vàng (văn bản, Điều, khoản); loại câu (tra cứu, tổng hợp nhiều Điều/luật, không có câu trả lời); câu hỏi viết theo giọng nhân viên, không chép lời luật | W + O duyệt mẫu | Kiểm tay 100% nhãn; phân bố theo nhóm và loại câu ghi trong manifest |
| (Phụ) Chạy cùng script đánh giá trên Zalo legal (corpus riêng) làm benchmark ngoài | W | Có số recall@k để so với công bố khác |
| Hybrid search: pgvector + Postgres full-text (tiếng Việt bỏ dấu/không bỏ dấu), trộn RRF; rerank tuỳ chọn qua gateway; tra trực tiếp khi câu hỏi nêu số Điều/số hiệu | W | Bật/tắt từng thành phần bằng config |
| Script đánh giá truy xuất: recall@k, MRR, nDCG theo loại câu; so 4 cấu hình (vector, BM25, hybrid, hybrid+rerank) | W | Bảng kết quả có seed, phiên bản, chi phí |

**DoD R1:** có bảng recall@5/@10 và MRR cho 4 cấu hình trên ~150 câu. Cấu hình mặc định được chọn theo số đo, không theo cảm tính. Toàn bộ chạy lại được bằng một lệnh.

## R2 — Câu trả lời có trích dẫn kiểm chứng được

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Định dạng trả lời: mỗi câu có mã trích `[n]` trỏ tới đoạn cụ thể (văn bản, Điều, khoản, vị trí ký tự); agent chỉ được trích đoạn đã truy xuất | W | Test: trích nguồn ngoài danh sách bị loại |
| Bộ kiểm chứng sau sinh: tách câu → kiểm từng câu có được đoạn trích hỗ trợ (LLM-judge `acme-judge`, JSON có cấu trúc); câu không được hỗ trợ bị gắn cờ hoặc bỏ; không đủ nguồn thì trả lời "không tìm thấy trong tài liệu" | W | Bật/tắt bằng config; đo được chi phí và độ trễ thêm |
| UI: bấm `[n]` mở đoạn nguồn, tô đúng câu được trích; hiển thị câu bị gắn cờ "chưa kiểm chứng" | W | Vitest + Playwright |
| Hiệu chuẩn judge: 30–50 câu chấm tay, Cohen's κ người–judge | O + R | Báo cáo κ |
| Đánh giá: citation precision/recall, faithfulness, tỉ lệ từ chối đúng với câu không có đáp án; có và không có bộ kiểm chứng | W | Bảng so sánh kèm chi phí/câu và độ trễ p50/p95 |

**DoD R2:** báo cáo được mức cải thiện của bộ kiểm chứng (citation precision, faithfulness) kèm khoảng tin cậy và chi phí. Câu hỏi không có đáp án trong tài liệu được từ chối đúng ở mức đo được.

## A1 — Hành động qua MCP và phân quyền theo vai trò

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Ma trận quyền vai trò × tool × kênh (dự thảo ở ADR-007), thực thi ở MCP server | O + W | Test mọi ô của ma trận, cả cho phép lẫn từ chối |
| tickets-mcp: `prepare_create_ticket` qua intent + phê duyệt ký số; router agent thêm nhánh tạo ticket | W | E2E tạo ticket xanh; từ chối thì không ghi gì |
| `notify-mcp`: port `MessageChannel`, adapter `telegram` + `fake`, tool `prepare_send_group_report`, bí danh kênh, mức mật theo kênh, profile `notify` | W | E2E gửi qua `fake`; chat ID tuỳ ý bị từ chối; dữ liệu vượt mức mật bị chặn; leak-grep rỗng |
| Eval hành động: chọn đúng tool và tham số, từ chối đúng khi thiếu quyền, không hành động khi chỉ hỏi | W | Bảng kết quả theo vai trò, chạy lại bằng một lệnh |
| Đo RAM khi bật `tickets` + `notify` | W | Bảng số đo thật trong README |

**DoD A1:** user tạo ticket và gửi báo cáo Telegram qua chat, có thẻ duyệt; ma trận quyền có test đầy đủ; thêm kênh mới chỉ là thêm file adapter.

## Q1 — Cache và quan sát

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Exact cache: khoá gồm model, prompt, phạm vi quyền; không cache thao tác ghi; giữ nguyên trích dẫn đã kiểm chứng | W | Test: khác phạm vi quyền thì không trúng cache |
| Đánh giá RQ4: hit rate, chi phí, độ trễ, chất lượng khi có/không cache; semantic cache ở dạng thử nghiệm, kèm đo rò rỉ | W | Bảng so sánh; semantic cache mặc định vẫn tắt |
| OpenTelemetry xuyên BFF → agent → gateway → MCP; chọn backend trace nhẹ ở profile `obs` | W | Một câu hỏi cho ra một trace đủ các hop |
| Log JSON có `trace_id`; dashboard Grafana: truy xuất, chi phí, cache, hành động | W | Dashboard chạy trên số thật |
| Trace và log không chứa nội dung prompt/tài liệu | W | Quét canary trên trace = 0 |

**DoD Q1:** có báo cáo RQ4; từ một câu hỏi lần ra được toàn bộ đường đi, chi phí và độ trễ từng hop.

## R3 — An toàn

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Kiểm tra rò rỉ: mỗi user trong 16 user hỏi bộ câu chạm tài liệu trái quyền; kiểm cả câu trả lời, trích dẫn, cache | W | 0 tài liệu trái quyền xuất hiện ở bất kỳ đâu |
| Tấn công qua hành động: tài liệu độc lừa agent tạo ticket hoặc gửi dữ liệu mật vào nhóm (dùng adapter `fake`) | W | Bảng ASR có/không từng lớp (phê duyệt, mức mật kênh, taint) |
| Xây corpus độc (`data/corpus/` hiện trống; ≥ 50 tài liệu, 8 kỹ thuật injection, có ground truth) và nạp vào kho; đo tỉ lệ tấn công thành công (ASR) có/không spotlighting và bộ kiểm chứng | W | Bảng ASR theo kỹ thuật |
| Canary trong tài liệu mật không bao giờ ra khỏi phạm vi quyền (log, response, usage) | W | Quét tự động = 0 |
| Security regression chạy trong CI | W | CI fail khi hồi quy |

**DoD R3:** rò rỉ trái quyền = 0 trên toàn bộ ca thử; có bảng ASR theo kỹ thuật injection, kèm số đo ảnh hưởng của từng lớp phòng thủ.

## R4 — Đánh giá tổng hợp, demo, báo cáo

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Ablation: bỏ từng thành phần (hybrid, rerank, kiểm chứng, spotlighting) → ảnh hưởng chất lượng, an toàn, chi phí | W | Bảng + biểu đồ |
| Chạy với ≥ 2 model thật (một rẻ, một mạnh) trong ngân sách cố định | W + O | Ngân sách và chi phí thực ghi rõ |
| Demo Playwright: đăng nhập → hỏi → câu trả lời có trích dẫn → mở nguồn; user khác phòng không thấy tài liệu mật; tạo ticket và báo cáo nhóm có thẻ duyệt | W | Xanh trên compose |
| Bản deploy gọn: VPS 4 GB, reverse proxy + HTTPS, hướng dẫn | W | Chạy được trên VPS thật |
| Báo cáo: phương pháp, số liệu, giới hạn, công bố seed/prompt/phiên bản | O + R | Hoàn chỉnh |

**DoD R4:** mọi số liệu trong báo cáo tái lập được bằng script trong repo; demo chạy trên VPS 4 GB.

## Ngoài phạm vi (đóng băng hoặc bỏ)

| Hạng mục | Tình trạng |
|---|---|
| analytics-mcp | Đóng băng, profile `analytics` |
| policy-sidecar (guard, NER) | Đóng băng, profile `sidecar` |
| Rate limit, budget đầy đủ, fallback nhiều provider, router chi phí | Bỏ (chỉ giữ ghi usage + chi phí) |
| Trang admin, i18n, HA, mTLS, Helm, secret manager | Bỏ |
