# Khảo sát dự án tương tự trên GitHub

Kiểm tra ngày 2026-11-01 bằng `gh search repos` (khoảng 45 truy vấn), `gh repo view`, và README của 10 repo qua `gh api`. Chỉ đọc README, không đọc code. Tìm kiếm chưa đầy đủ: "không thấy" nghĩa là không tìm được theo cách trên, không phải khẳng định không tồn tại.

## Kết luận

Không tìm thấy dự án mở nào có đủ tổ hợp: trích dẫn kiểm chứng sau sinh, phân quyền ở tầng DB, hành động MCP có duyệt, cache theo quyền, tiếng Việt. Các nền tảng lớn có từng phần. Vì vậy giữ hướng tự xây lõi và dùng lại công cụ quan sát, eval.

## Nền tảng gần nhất

"—" là không thấy trong README, không có nghĩa là sản phẩm không có.

| Repo | Sao | License (GitHub) | Trích dẫn | Phân quyền | MCP | Quan sát |
|---|---|---|---|---|---|---|
| langgenius/dify | 160.156 | Other (có điều kiện thêm) | — | SSO, RBAC ở bản Enterprise | Agent/workflow | — |
| open-webui/open-webui | 157.459 | Other (giữ branding) | Không rõ | RBAC, nhóm người dùng | MCP/OpenAPI tools | OpenTelemetry |
| infiniflow/ragflow | 93.291 | Apache-2.0 | "traceable citations" | — | — | — |
| Mintplex-Labs/anything-llm | 67.814 | MIT | "source citations" | Multi-user (bản Docker) | Có | — |
| zylon-ai/private-gpt | 57.625 | Apache-2.0 | "Retrieval with citations" | Có vẻ ở bản thương mại Zylon | Remote MCP | — |
| onyx-dot-app/onyx | 33.141 | Other (CE/EE tách riêng, phải đọc LICENSE) | Chưa xác nhận | Phân quyền chi tiết; SSO/SCIM/RBAC ở mục Enterprise | MCP, Actions | — |
| Cinnamon/kotaemon | 25.845 | Apache-2.0 | Có xem trước tài liệu | — | — | — |

Không nền tảng nào ở trên có README nói về duyệt thao tác ghi, cache theo quyền, hay tiếng Việt.

**Tham khảo thiết kế (repo nhỏ):**
- humorless/levinrag (4 sao, Apache-2.0): lọc quyền ngay trong truy xuất, test từng cặp tài liệu × user không có quyền. Rất gần cách ta kiểm rò rỉ ở R3.
- kgorle1111/permission-aware-rag (2 sao, Apache-2.0): lọc ACL trước khi xếp hạng. Kết quả "0 leaks" là tự báo cáo, chưa kiểm chứng.
- mikeethanh/Vietnamese-Legal-Chatbot-RAG-System (21 sao, MIT): RAG luật Việt Nam, không thấy phân quyền.

## Dùng lại được gì

| Nhu cầu | Ứng viên | Kết luận |
|---|---|---|
| Trace cho LangGraph/LLM theo OTel | traceloop/openllmetry (7.515 sao, Apache-2.0) | Ứng viên chính ở Q1 |
| Giao diện trace, eval, dataset | langfuse/langfuse (36.832 sao, GitHub ghi Other; README ghi MIT trừ `ee`) | Chỉ thêm nếu backend nhẹ không đủ; đọc LICENSE trước |
| Eval | confident-ai/deepeval (19.226 sao, Apache-2.0), vibrantlabsai/ragas (16.203 sao, Apache-2.0, push cuối 2026-02-24) | Chạy đối chứng cạnh metric tự viết, không thay thế; chưa kiểm metric cụ thể và hỗ trợ tiếng Việt |
| MCP ticket ngoài | github/github-mcp-server, sooperset/mcp-atlassian | Không cần: ta dùng `tickets-mcp` nội bộ |
| Gửi Telegram | chigwell/telegram-mcp (1.948 sao, Apache-2.0) | **Không dùng:** README yêu cầu API ID và session string, tức chạy bằng tài khoản người dùng (Telethon), không phải bot |
| Gửi Slack | korotovsky/slack-mcp-server (1.882 sao, MIT) | Không dùng cho bản đầu; README nói "no permission requirements", phải rà soát quyền |
| Gửi Zalo OA | Không có repo đáng tin; ardennguyen/zalo-mcp có license cấm thương mại | Tự viết adapter nếu làm |
| Cache | zilliztech/GPTCache (8.218 sao, MIT) | Không dùng: README không có cách ly theo quyền; ta đã có adapter riêng |

Lý do tự viết `notify-mcp`: các MCP nhắn tin có sẵn đều cho agent toàn quyền tài khoản, không có bí danh kênh, mức mật hay phê duyệt. Những thứ đó chính là phần ta cần đo ở RQ3.

## Khoảng trống

- **Kiểm chứng trích dẫn sau sinh theo từng câu:** không thấy trong nền tảng lớn; `ragflow` nói "verify" nhưng là trong vòng lặp truy xuất. Repo có tên citation verification đều rất nhỏ (dưới 4 sao).
- **RLS + pgvector cho RAG:** có một số repo 0–1 sao (ví dụ buildwithmoses/supabase-agents), không thấy dự án đáng kể nào. Chưa đọc code các repo này.
- **Cache semantic cách ly theo quyền:** chỉ thấy repo 0–1 sao, không có license.
- **Phê duyệt thao tác ghi cho MCP nhắn tin/ticket:** không thấy trong repo có sao đáng kể.
- **Tiếng Việt:** nhiều repo RAG luật nhỏ, không thấy repo nào có phân quyền hoặc trích dẫn kiểm chứng.

Đây là chỗ đề tài có đóng góp riêng, nhưng cần đọc thêm bài báo khoa học trước khi khẳng định "mới": khảo sát này chỉ nhìn GitHub.

Chưa đọc README: khoj-ai/khoj, danny-avila/LibreChat, QuivrHQ/quivr, SciPhi-AI/R2R. ViLegalREB (benchmark truy xuất luật tiếng Việt, không có license) có thể đáng xem làm tham khảo dữ liệu.
