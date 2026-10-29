# ADR-004: Mã hoá checkpoint LangGraph bằng `EncryptedSerializer` + quy tắc đặt dữ liệu vào state

- **Trạng thái:** Đã chấp nhận (2026-10-29), sau Spike D (M0).
- **Người quyết định:** orchestrator; chủ dự án review
- **Bằng chứng:** `spikes/d_checkpoint_encryption/{README.md,output.txt}`, `docs/research/05-m0-verification.md` §6
- **Liên quan:** `docs/design/03-agent-ui.md` (checkpoint, HITL), contracts §7 (`AGENT_CHECKPOINT_ENCRYPTION_KEY`)

## Bối cảnh
Thiết kế 03 giả định checkpoint "được mã hoá mặc định". Spike D chạy trên `langgraph-checkpoint` 4.3.1 và `langgraph-checkpoint-postgres` 3.2.0, rồi kiểm trực tiếp bằng SQL.

Kết quả với `EncryptedSerializer` (AES-EAX):

| Cột | Kết quả |
|---|---|
| `checkpoint_blobs.blob` (chứa `messages`, list/dict) | Ciphertext |
| `checkpoint_writes.blob` (gồm payload `interrupt()`) | Ciphertext |
| `checkpoints.checkpoint` (JSONB) | **Plaintext** với channel kiểu đơn giản (`str`/`int`/`float`/`bool`/`None`): giá trị được chép nguyên văn vào `channel_values` |
| `checkpoints.metadata` (JSONB) | **Plaintext**: chứa mọi key của `config["configurable"]`, trừ `thread_id` |

Ngoài ra:
- Resume sau `interrupt` bằng một tiến trình mới chạy đúng.
- Sai key thì lỗi `ValueError: MAC check failed`.
- Mặc định là `JsonPlusSerializer`, **không mã hoá**. `PostgresSaver.from_conn_string()` bản đồng bộ không nhận `serde`.

## Quyết định
1. **Dựng saver tường minh:** `PostgresSaver(conn, serde=...)` hoặc `AsyncPostgresSaver(pool, serde=...)`, với `serde = EncryptedSerializer.from_pycryptodome_aes(key=<bytes>)`. Thêm `pycryptodome` vào dependency của `packages/agent`.
2. **Key:** `AGENT_CHECKPOINT_ENCRYPTION_KEY` là **base64 của 32 byte** ngẫu nhiên, hỗ trợ `_FILE`. Agent tự `b64decode`, kiểm độ dài 32 byte, sai thì từ chối khởi động. **Không** dùng biến `LANGGRAPH_AES_KEY`. Bắt buộc ngoài `ACME_ENV=test`, như contracts §7.
3. **Quy tắc state, bắt buộc và có review:**
   - Nội dung nhạy cảm chỉ đặt trong `messages` hoặc channel có kiểu non-primitive (dict/list/pydantic). Nội dung nhạy cảm gồm: hội thoại, kết quả tool, `intent_jws`, pending action, tóm tắt.
   - Channel kiểu `str`/`int` chỉ dùng cho cờ, bộ đếm, ID không nhạy cảm.
   - `config["configurable"]` **chỉ** chứa `thread_id` (và `checkpoint_ns` nếu cần). Token và dữ liệu người dùng truyền qua `context=` hoặc contextvar.
4. **Test bắt buộc trong CI** (Postgres thật): sau một lượt chạy có chuỗi canary và một lần `interrupt`, chuỗi canary không được xuất hiện trong `checkpoints.checkpoint::text`, `metadata::text` hay `encode(blob,'escape')`. Test chạy lại mỗi lần nâng phiên bản LangGraph.
5. Không dùng phương án B (pgcrypto ở lớp lưu trữ).

## Hệ quả
- (+) Nội dung hội thoại và payload phê duyệt được mã hoá at-rest, chỉ cần một tham số `serde`.
- (−) **Rủi ro còn lại, đã chấp nhận:**
  - Không có AAD: bản mã chép sang thread khác vẫn giải mã được.
  - Xoay khoá cần cipher tự viết có `kid`, đẩy sang M7.
  - `loads_typed` vẫn đọc được dữ liệu không mã hoá, nên kẻ có quyền ghi DB có thể chèn plaintext. Giảm thiểu bằng phân quyền role `ag_app` và audit.
  - `thread_id`, `step` và kích thước blob vẫn lộ.
  - Hành vi phụ thuộc cách thư viện phân loại kiểu primitive. Test ở mục 4 là chốt chặn.
- Việc kéo theo: sửa `docs/design/03-agent-ui.md` (bỏ "mã hoá mặc định", thêm quy tắc state); bản async `AsyncPostgresSaver` kiểm lại ở M1.
