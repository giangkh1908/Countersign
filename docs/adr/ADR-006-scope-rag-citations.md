# ADR-006: Thu hẹp đề tài về trợ lý tri thức nội bộ có trích dẫn kiểm chứng được

> Ghi chú: các thành phần đóng băng nêu dưới đây (analytics-mcp, policy-sidecar, spikes, benchmark) đã bị xoá theo dọn dẹp 2026-11-01; bản cũ ở git tag `backup/pre-prune-20261101`. Phần còn lại giữ nguyên văn lịch sử.

- Trạng thái: Đã chấp nhận (2026-10-30). Phần phạm vi ticket, cache, quan sát được sửa bởi [ADR-007](ADR-007-actions-cache-observability.md).
- Thay thế phạm vi của lộ trình v1.3 (M2–M7, xem git tag `backup/pre-prune-20261101`). Không thay các quyết định về bảo mật, identity, Ports & Adapters.

## Bối cảnh

Đề tài v1.3 gồm gateway đầy đủ, 3 MCP server, luồng ghi có phê duyệt ký số, policy-sidecar, quan sát (Langfuse, Prometheus/Grafana), trang admin và production hardening. Phạm vi quá rộng so với thời gian và tài nguyên. Bản đầy đủ cần khoảng 14–16 GB RAM, trong khi 11 service lõi chỉ dùng khoảng 1,3 GB lúc rảnh (đo 2026-10-30). Kết quả nghiên cứu bị dàn mỏng trên nhiều hướng.

M1 đã chạy đầu-cuối trên compose: đăng nhập Keycloak qua BFF, agent LangGraph, gateway, docs-mcp có ACL/RLS, và luồng đóng ticket có phê duyệt (E2E 56/56).

## Quyết định

Đề tài mới: **trợ lý tri thức nội bộ doanh nghiệp, trả lời từ tài liệu công ty và trích dẫn kiểm chứng được, có phân quyền theo người dùng.**

Câu hỏi nghiên cứu:
1. **Truy xuất:** hybrid (vector + từ khoá) và rerank cải thiện recall@k bao nhiêu trên tài liệu tiếng Việt so với chỉ vector hoặc chỉ BM25?
2. **Trích dẫn:** một bước kiểm chứng sau sinh (mỗi câu ↔ đoạn nguồn được trích) nâng citation precision và faithfulness bao nhiêu, đổi lại chi phí và độ trễ bao nhiêu?
3. **An toàn:** với ACL ở tầng DB (RLS) và spotlighting, tỉ lệ rò tài liệu trái quyền và tỉ lệ tấn công thành công của tài liệu độc (prompt injection gián tiếp) là bao nhiêu?

Giữ lại:
- Keycloak + BFF + SPA: đăng nhập thật, token chỉ ở BFF.
- Gateway bản mỏng: auth key, `/v1/chat/completions`, thêm `/v1/embeddings`, `usage_events` + chi phí đơn giản. Chi phí mỗi câu trả lời là một số đo.
- docs-mcp: ACL/RLS, spotlighting, taint.
- Agent LangGraph: router rút gọn, chỉ còn docs và trả lời trực tiếp.
- Hash-chain audit, các quy tắc Ports & Adapters.

Đóng băng: giữ code và test, tắt khỏi compose mặc định qua profile:
- tickets-mcp, approval-signer, luồng intent/approval (profile `tickets`).
- analytics-mcp (`analytics`), policy-sidecar (`sidecar`), Prometheus/Grafana (`obs`), Langfuse.

Bỏ khỏi lộ trình:
- Trang admin, i18n.
- HA, mTLS, Helm, secret manager (M7 cũ).
- Router chi phí E3, semantic cache, user study thẻ duyệt.

## Dữ liệu

Chi tiết nguồn, giấy phép, checksum ở [`data/SOURCES.md`](../../data/SOURCES.md).

- **Corpus chính:** 19 luật/bộ luật Việt Nam đang hiệu lực, tải từ CSDL quốc gia về pháp luật (vbpl.vn), tách được 1.557 Điều
  (khoảng 1,8 triệu ký tự). Mỗi luật đóng vai một bộ "quy định" mà nhân viên ACME cần tra cứu. Văn bản quy phạm pháp luật không
  được bảo hộ quyền tác giả nên dùng và công bố lại được.
- **Phân quyền là giả lập, gán tất định theo chủ đề:** nhóm nhân sự → `HR`, nhóm CNTT/bảo mật → `IT`, nhóm tài chính và pháp chế → `ALL`.
  Tài liệu mật (c2/c3, có canary) vẫn là 30 tài liệu ACME tổng hợp; đây là phần dùng để đo rò rỉ.
- **Bộ câu hỏi tự xây:** sinh nháp bằng LLM từ từng Điều, người kiểm tay, nhãn vàng là (văn bản, Điều, khoản). Lý do: bộ có nhãn sẵn
  (Zalo legal) chỉ có 27/3.298 cặp nhãn rơi vào corpus đã chọn, phần lớn là xử phạt giao thông. Zalo chỉ dùng làm benchmark truy xuất
  ngoài, trên corpus riêng của nó.
- **Đã loại UTS_VLC làm corpus:** một nửa số dòng có tiêu đề không khớp nội dung (ví dụ dòng "Bộ luật Lao động" chứa kế hoạch của một UBND tỉnh).

Thay đổi khung cần làm (đưa vào R1):
1. Loader mới `vbpl_articles` (port `DocumentLoader` đã có): đọc JSON Điều, mỗi Điều là một đơn vị; Điều dài cắt theo khoản, giữ `article`/`clause` trong metadata chunk.
2. `knowledge.chunks` thêm cột vị trí trích dẫn (`article`, `clause`, `char_start`, `char_end`) để UI mở đúng đoạn và bộ kiểm chứng đối chiếu được.
3. Số chiều embedding không cứng `vector(1024)`: chọn model trước, migration theo số chiều đó, ghi vào config và kiểm khi khởi động.
4. Gateway `/v1/embeddings` + port `EmbeddingProvider` (như mục Giữ lại).
5. Full-text tiếng Việt: giữ `unaccent`, thêm thử nghiệm tách từ (ví dụ ghép âm tiết) làm một cấu hình trong RQ1.

## Hệ quả

- Compose mặc định chạy trên VPS 2–4 vCPU, 4 GB RAM. Mục tiêu: dưới 2,5 GB RAM lúc rảnh, đo và ghi vào README.
- Embedding gọi qua gateway (`acme-embed`) tới API provider. Không chạy model nặng tại chỗ. Thêm port `EmbeddingProvider` phía gateway; mỗi vendor một adapter.
- Đánh giá xoay quanh một bộ câu hỏi có nhãn (đoạn nguồn đúng), corpus độc `data/corpus/`, và kiểm tra rò rỉ theo user/phòng ban.
- Nếu sau này mở rộng lại, thiết kế cũ nằm ở git tag `backup/pre-prune-20261101`.
