# Phê duyệt thao tác ghi (What You See Is What You Sign)

Mọi thao tác ghi của agent đi qua một luồng duy nhất: tickets-mcp tính và ký **intent**, approval-signer dựng thẻ duyệt từ intent đó và ký **approval** khi người dùng bấm Duyệt, rồi tickets-mcp mới ghi. Agent không quyết định nội dung được xem lẫn nội dung được ký. Code ở `packages/mcp_tickets`, `packages/approval_signer`, `packages/bff`; chạy với `--profile tickets`. Luồng này hiện có một thao tác (`close_ticket`); `notify-mcp` sẽ dùng lại ở A1.

## 1. Mô hình đe doạ

| Chủ thể | Mức tin cậy |
|---|---|
| Người dùng duyệt | Là người ra quyết định; có thể mệt hoặc bị đánh lừa bởi nội dung hiển thị |
| Agent và LLM | Không tin cậy: có thể bị prompt injection, bị chiếm hoặc có bug |
| Nội dung tài liệu, ticket | Không tin cậy (injection lưu trữ) |
| tickets-mcp | Tin cậy: giữ khoá intent, đọc DB, thực thi ghi |
| approval-signer | Tin cậy: giữ khoá approval, nhỏ để review được (chỉ FastAPI, PyJWT, cryptography) |
| BFF | Tin cậy một phần. Bị chiếm là rủi ro còn lại (mục 5) |
| Keycloak, Postgres, Redis | Tin cậy (hạ tầng) |

| Mối đe doạ | Biện pháp |
|---|---|
| Agent đề xuất thao tác khác ý người dùng (đóng ticket khác kèm lời giải thích đẹp) | Thẻ chỉ lấy từ intent do MCP tính; mã ticket, `before`, `after` hiển thị đúng đối tượng sẽ bị ghi |
| Agent tráo tham số giữa lúc duyệt và lúc ghi | `commit_intent` không nhận tham số. MCP thực thi `args_canonical` lấy từ intent đã lưu; approval gắn `intent_sha256` |
| Agent tự dựng intent giả | Signer chỉ nhận intent có chữ ký ES256 của MCP (khoá công khai mount sẵn, theo `iss` và `kid`) |
| Agent tự xin approval | Agent không có token `aud=approval-signer` và Keycloak từ chối exchange. Signer kiểm `aud`, `azp=chat-ui`, scope `signer:approve`, `sub == intent.sub` |
| Phát lại approval, commit hai lần song song | `jti` dùng `SET NX`; Lua CAS trạng thái intent gắn `owner_jti`; `UNIQUE(ticket_events.intent_id)` ở DB độc lập với Redis |
| Ticket bị sửa giữa prepare và commit (TOCTOU) | `expected_updated_at` nằm trong intent đã ký; UPDATE có điều kiện, 0 dòng thì `conflict` |
| Approval của user A dùng cho phiên user B | Ba điểm kiểm `sub`: signer, `commit_intent`, `actor_sub` trong DB |
| Agent đọc tài liệu mật rồi ghi vào ticket mà người cấp thấp đọc được | Taint (mục 4): cờ `possible_downgrade`, UI cảnh báo đỏ, chính sách `warn` hoặc `block` |
| Người dùng "Sửa" rồi ký tham số do UI dựng | Nhánh Sửa gọi lại `prepare_*`, tạo intent mới; không có đường ký tham số do UI hay agent dựng |
| Thẻ giấu nội dung (trường được ký mà thẻ không hiển thị, ký tự bidi) | `display_fields` phủ toàn bộ `args_canonical` và `before`, `after`; trường không hiển thị được thì `422 intent_unrenderable`, không có thẻ. BFF và SPA escape ký tự bidi và điều khiển thành dạng nhìn thấy được |
| Duyệt phản xạ | Thẻ ngắn, diff rõ, cờ rủi ro; giới hạn số thẻ (mục 3) |

## 2. Các bước

1. **Prepare.** Agent gọi `prepare_close_ticket(code, resolution)` (scope `tickets:write`, không đổi dữ liệu). tickets-mcp kiểm quyền, đọc ticket qua RLS, chuẩn hoá tham số, tính `before` và `after`, đọc taint, dựng `risk_flags`, ký intent JWS bằng khoá intent, lưu vào Redis và trả `{intent_id, intent_jws, expires_at}`.
2. **Interrupt.** Agent gọi `interrupt({kind: "write_approval", intent_jws, intent_id})` và dừng. Agent không dựng preview.
3. **Verify và render.** SPA gọi `POST /api/intents/verify`; BFF chuyển sang `POST /v1/intents/verify` của signer kèm token `aud=approval-signer` của phiên. Signer kiểm chữ ký MCP, `exp`, `sub`, tính hiển thị được, rồi trả render model (`display_fields`, `before`, `after`, `risk_flags`, `intent_sha256`, `server_time`) hoặc `422 intent_unrenderable`. SPA chỉ vẽ render model, mọi chuỗi là văn bản thuần.
4. **Approve.** Người dùng bấm Duyệt; BFF gọi `POST /v1/approvals`. Signer kiểm lại toàn bộ rồi ký approval token ES256 (hiệu lực 120 giây).
5. **Resume.** BFF resume agent với `{decision: "approve", approval_token}`; agent gọi `commit_intent(intent_id, approval_token)`.
6. **Commit.** tickets-mcp thực hiện các kiểm tra ở mục 2.2, rồi ghi trong một transaction cùng `ticket_events` và `tool_audit`.

Nhánh khác:
- **Sửa:** quay lại bước 1 với tham số mới, ra intent mới.
- **Từ chối:** BFF ghi `intent_id`, `intent_sha256` và `content_sha256` (băm của `{op, target, args_canonical}`) vào `bff:sess:{sid}:rej` (TTL 10 phút) rồi mới resume agent. Thẻ trùng một giá trị trong tập này bị BFF trả `409 conflict`, không gọi signer. Intent tự hết hạn, không có tool huỷ.
- **Approval quá 120 giây:** `approval_expired`; nếu intent còn hạn thì người dùng bấm Duyệt lại.
- **Intent quá hạn:** signer trả `410 intent_expired`; agent chỉ gọi lại `prepare_*` khi người dùng muốn tiếp tục.

### 2.1 Artefact

- `canonical_json`: khoá sắp xếp, không khoảng trắng, UTF-8, chuỗi chuẩn hoá NFC, không chấp nhận float. Hàm duy nhất ở `acme_common/services/canonical.py`, signer và MCP dùng chung, có test vector cố định.
- **Intent JWS** (ES256, `typ=acme-intent+jws`): `iss=tickets-mcp`, `aud=approval-signer`, `sub` là người gọi `prepare_*` (lấy từ JWT đã verify, không phải tham số), `iat`, `exp = iat + 300`, `intent_id`, `op`, `target`, `before`, `after`, `expected_updated_at`, `args_canonical` (chuỗi), `risk`, `risk_flags`. Tối đa 8 KiB. `risk_flags`: `destructive`, `internal_comment`, `priority_urgent`, `possible_downgrade`, `taint_unknown`.
- **Approval token** (ES256, `typ=acme-approval+jwt`): `iss=acme-approval`, `aud=tickets-mcp`, `sub`, `intent_id`, `intent_sha256`, `jti`, `exp - iat <= 120`.
- `intent_sha256 = sha256(canonical_json(payload intent))`, tính từ payload đã verify, không từ chuỗi do client gửi.
- Redis `mcp:tickets:intent:{id}` là HASH `{jws, sha256, sub, status, owner_jti, updated_at}`, TTL bằng `exp` cộng 30 giây. Chỉ Redis user `tickets` đọc được khoá này.
- Khoá: mỗi MCP một cặp khoá intent, signer một cặp khoá approval. Header `kid` lạ thì từ chối, không tải khoá từ mạng. Xoay khoá: phát khoá công khai mới trước, đổi `kid` ở bên ký, giữ khoá công khai cũ ít nhất 15 phút rồi xoá.

### 2.2 Kiểm tra trong `commit_intent`

| # | Kiểm tra | Lỗi |
|---|---|---|
| 1 | Có `approval_token` | `approval_required` |
| 2 | `alg=ES256`, `typ`, `kid` thuộc tập tin cậy; chữ ký, `iss`, `aud` | `approval_invalid` |
| 3 | `exp` còn hạn, `exp - iat <= 120` | `approval_expired` |
| 4 | `sub == caller.sub` | `approval_mismatch` |
| 5 | Intent có trong Redis và còn hạn | `intent_not_found`, `intent_expired` |
| 6 | `jws` đọc từ Redis được verify lại bằng khoá MCP; `intent.sub == caller.sub`; `intent.sha256` bằng `approval.intent_sha256` (so sánh hằng thời gian) | `intent_mismatch` |
| 7 | Phân quyền lại với người gọi hiện tại (xem, sửa, máy trạng thái ticket) | `not_found`, `forbidden`, `conflict` |
| 8 | `SET mcp:tickets:jti:{jti} NX EX 180` | `approval_replayed` |
| 9 | CAS `pending` sang `committing` (mục 2.3) | `approval_replayed`, `intent_mismatch` |
| 10 | Thực thi một transaction với `WHERE updated_at = expected_updated_at` | `conflict`, `approval_replayed` |
| 11 | Redis lỗi | `upstream_unavailable` (đóng an toàn) |

### 2.3 Máy trạng thái intent

```
pending --Lua CAS (owner_jti = approval.jti)--> committing --DB ok--> committed
                                                committing --expected_updated_at lệch--> failed   (lỗi conflict)
                                                committing --UNIQUE(intent_id) vi phạm--> committed (lỗi approval_replayed)
mọi trạng thái --key hết TTL--> biến mất => intent_expired hoặc intent_not_found
```

- Chỉ approval giữ `owner_jti` được chuyển `committing` sang `committed` hoặc `failed`. Hai approval khác `jti` cho cùng intent thì chỉ một bên thắng CAS.
- Gặp `committing` (dưới 30 giây) hoặc `committed` thì trả `approval_replayed`. Gặp `failed` thì `intent_mismatch` (`reason=failed`), phải `prepare_*` lại.
- Tiến trình chết giữa chừng: `committing` quá 30 giây thì lần gọi sau tra `ticket_events.intent_id`; có thì coi là `committed`, không thì `failed`.
- Không có trạng thái `cancelled` hay `aborted`. Lỗi hạ tầng xác định (rollback) thì `failed`; không xác định thì để `committing` chờ khôi phục. `jti` đã đốt nên người dùng làm lại bằng intent mới.

## 3. Ràng buộc ở signer và BFF

- Signer chạy ở mạng `core`, không egress, không DB, không Redis. Có `/v1/intents/verify` (không ký) và `/v1/approvals` (kiểm lại rồi ký). Giới hạn 30 approval mỗi giờ mỗi `sub` trong bộ nhớ.
- Signer đòi token `aud=approval-signer` đúng một phần tử, `azp=chat-ui`, scope `signer:approve`, `sub` bằng `intent.sub`.
- `display_fields` mỗi phần tử gồm `path, label, kind, before, after, changed, sensitive`; `kind` thuộc `text|longtext|enum|datetime|ticket_ref`. SPA gặp `kind` lạ thì cảnh báo và vô hiệu nút Duyệt.
- BFF giữ token `aud=approval-signer` theo phiên (TTL tối đa 5 phút), không bao giờ gửi cho agent hay trình duyệt, và không giữ khoá ký.
- BFF giới hạn tối đa 10 thẻ duyệt mỗi thread mỗi giờ (`BFF_MAX_CARDS_PER_THREAD_HOUR`); vượt thì `429 rate_limited`. Giới hạn đặt ở BFF để không dựa vào agent.

## 4. Taint

docs-mcp và tickets-mcp (`get_ticket`) ghi taint vào Redis khi trả dữ liệu có cấp mật: `mcp:taint:{sub}:{thread_id}` và `mcp:taint:{sub}:recent` (24 giờ), gồm `max_class` và tập phòng ban nguồn. Khi `prepare_*`, tickets-mcp so `max_class` với cấp thấp nhất của đối tượng sẽ thấy bản nháp (`acme.ticket_audience`). Cao hơn thì gắn `possible_downgrade`; không đọc được taint thì gắn `taint_unknown`. `TAINT_POLICY` là `warn` (mặc định, chỉ cảnh báo trên thẻ) hoặc `block` (từ chối prepare). Taint không phân tích nội dung nên có thể báo thừa; nó là tín hiệu cho người duyệt, không phải rào cản duy nhất.

## 5. Rủi ro còn lại

1. **BFF bị chiếm** có thể hiện thẻ giả và xin signer ký approval cho intent thật của chính user đó, vì nó giữ token exchange của user. Intent của người khác thì không. Giảm thiểu: BFF nhỏ, không chạy code LLM, CSP `script-src 'self'`. Step-up xác thực (WebAuthn, CIBA) để chứng minh có mặt người dùng chưa làm.
2. **Người dùng duyệt nhầm** dù thẻ đúng. Chưa có số đo user study.
3. **Taint thô** có thể báo thừa hoặc bỏ sót, vì chỉ dựa vào cấp mật của thứ đã đọc.
4. **Chiếm tickets-mcp** là chiếm luôn khoá intent: ngoài phạm vi; giảm bằng tách khoá theo MCP và role DB tối thiểu.
5. Kẻ có quyền ghi Redis và khoá HMAC audit cùng lúc không bị chống bởi thiết kế này.
