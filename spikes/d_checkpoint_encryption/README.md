# Spike D: mã hoá checkpoint LangGraph trên Postgres

**Kết luận: ĐẠT CÓ ĐIỀU KIỆN.** `EncryptedSerializer` mã hoá đúng blob và interrupt payload, resume sau restart (tiến trình mới) đúng, sai key lỗi rõ. NHƯNG `checkpoints.checkpoint` (JSONB) và `checkpoints.metadata` vẫn là plaintext: channel kiểu primitive (str/int/float/bool/None) bị inline vào JSONB, và `config["configurable"]` bị copy vào metadata. Cần 2 quy tắc code bên dưới.

Phiên bản: langgraph-checkpoint-postgres 3.2.0, langgraph-checkpoint 4.3.1, Postgres pgvector/pg17 (container riêng cổng 55432, đã xoá).

## Chạy lại
```
docker run -d --name spike-d-pg -e POSTGRES_PASSWORD="$SPIKE_D_PG_PASSWORD" -p 55432:5432 pgvector/pgvector:pg17   # export SPIKE_D_PG_PASSWORD=<tự chọn> trước
uv run --no-project --with langgraph --with langgraph-checkpoint-postgres --with "psycopg[binary]" --with pycryptodome python spikes/d_checkpoint_encryption/spike.py
docker rm -f spike-d-pg
```
Script chạy 3 chế độ (`enc` = key qua `LANGGRAPH_AES_KEY`, `plain` = đối chứng, `b64` = key base64 giải mã rồi truyền `key=bytes`). Mỗi bước phase1/wrongkey/resume là một subprocess riêng (mô phỏng restart). Output thật: `output.txt`.

## Bảng cột nào ciphertext / plaintext (đo bằng SQL, đếm hàng chứa chuỗi bí mật)
| Cột | Có EncryptedSerializer | Không mã hoá |
|---|---|---|
| `checkpoint_blobs.blob` (channel không-primitive: `messages`, list/dict...) | ciphertext (0 hit, type `msgpack+aes`) | plaintext (1 hit) |
| `checkpoint_writes.blob` (gồm channel `__interrupt__`, payload interrupt) | ciphertext (0 hit) | plaintext (3 hit) |
| `checkpoints.checkpoint` JSONB `channel_values` | **PLAINTEXT** cho channel primitive (`note: "SECRET-...-note"`) | plaintext |
| `checkpoints.metadata` JSONB | **PLAINTEXT**: chứa `step, source, parents` và mọi key của `config["configurable"]` ngoài thread_id (đã thấy `user_note`) | plaintext |
Channel bọc trong list (`box: [secret]`) thì vào blob và được mã hoá; không xuất hiện trong JSONB.

## Trả lời các câu hỏi
- Giá trị channel nhỏ/primitive có inline vào JSONB không? CÓ. Chuỗi `str` thuần ở channel riêng nằm nguyên văn trong `checkpoints.checkpoint->channel_values` (không mã hoá). `messages` (add_messages) luôn vào blob nên an toàn.
- Payload `interrupt()` nằm ở đâu? `checkpoint_writes` (channel `__interrupt__`), được mã hoá. Không vào JSONB/metadata.
- Metadata: `configurable` bị ghi plaintext. Design 03 đã nghi ngờ điều này; đã xác nhận.
- (c) Resume bằng tiến trình mới: đọc lại đúng, node C chạy: `['SECRET-... luong cua nhan vien', 'C ran, decision=approved']`.
- (d) Sai key: `ValueError: MAC check failed` (EAX có tag xác thực), không trả rác.

## Khuyến nghị cho `packages/agent`
1. Dựng saver: `PostgresSaver(conn, serde=EncryptedSerializer.from_pycryptodome_aes(key=raw_bytes))` (async: `AsyncPostgresSaver(pool, serde=...)`, cùng tham số `serde`; chưa chạy bản async trong spike này). Không dùng `from_conn_string` đồng bộ (không nhận serde).
2. Định dạng key: hàm nhận `key: bytes` trực tiếp nên KHÔNG cần chuỗi thô 32 ký tự và KHÔNG cần env `LANGGRAPH_AES_KEY`. Cho `AGENT_CHECKPOINT_ENCRYPTION_KEY` là base64 của 32 byte ngẫu nhiên, tự `b64decode`, kiểm độ dài 16/24/32, truyền `key=`. Đã chạy chế độ `b64`: đạt cả (a)(c)(d).
3. Quy tắc state: (i) mọi nội dung nhạy cảm (nội dung user, kết quả tool, `intent_jws`, `pending_action`) phải ở channel `messages` hoặc kiểu không-primitive (dict/list/pydantic/dataclass); KHÔNG để str/int thuần chứa PII. Channel primitive chỉ cho cờ/đếm/id không nhạy cảm (`summary` nếu là str thuần thì LỘ: bọc dict). (ii) Không đặt dữ liệu người dùng/token vào `config["configurable"]` (chỉ `thread_id`); truyền qua `context=`/contextvars. Thêm test CI: chạy graph mẫu rồi `select ... where checkpoint::text like secret or metadata::text like secret` phải rỗng.
4. Retention ngắn + `adelete_thread` vẫn cần (JSONB còn `thread_id`, step, các id không nhạy cảm).

## Rủi ro còn lại
- Cipher có sẵn dùng AES-EAX, không có AAD: bản mã có thể bị chép sang thread/row khác và vẫn giải mã được. Muốn gắn `thread_id` làm AAD hoặc `kid` xoay khoá thì phải viết cipher riêng theo `CipherProtocol` (encrypt/decrypt chỉ nhận bytes, không biết thread_id, nên AAD theo thread khó; chấp nhận hoặc dùng cipher có `kid` trong ciphername để xoay khoá).
- `loads_typed` vẫn đọc được dữ liệu không có hậu tố `+aes` (hạ cấp im lặng): hàng cũ/plaintext do kẻ có quyền ghi DB chèn vào vẫn được nạp. Nên có test và quyền ghi DB hạn chế.
- Phụ thuộc cách phân loại primitive của thư viện: nâng version cần chạy lại test SQL ở mục 3.
- Mã hoá chưa che: độ dài blob, số lượng/thứ tự bước, `thread_id`, `checkpoint_id`.
- Phương án B (pgcrypto) không cần ở mức này nếu tuân thủ quy tắc 3.
