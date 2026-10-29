# 05 — Phê duyệt ràng buộc giao dịch (What You See Is What You Sign)

> Phiên bản 1.2, 2026-10-28. Tuân thủ `DECISIONS-v1.2.md` (D1, D7, D8, D10; file đó thắng mọi mâu thuẫn) và `00-contracts.md` (mọi điểm cần đổi contracts nằm ở mục 14 "Phụ thuộc contracts v1.2").
> Đây là tài liệu trung tâm của điểm khác biệt sản phẩm: **agent ghi dữ liệu nghiệp vụ nhưng không bao giờ tự quyết nội dung người dùng được thấy lẫn nội dung được ký**. Liên quan: `02-mcp-servers.md` (tickets-mcp: `prepare_*`/`commit_intent`), `03-agent-ui.md` (interrupt, UI), `04-evaluation.md` (E4).
> Code là minh hoạ thiết kế, chưa nằm trong repo. Chỗ API thư viện chưa xác minh ghi **[SPIKE]**.

## 0. Tóm tắt

| Điều | Luồng cũ (v1.1) | Luồng v1.2 (D1) |
|---|---|---|
| Ai dựng thẻ duyệt | Agent (preview từ `get_ticket` + args do LLM đề xuất) | **tickets-mcp** tính `intent` từ DB, ký JWS; agent chỉ chuyển tiếp |
| UI hiển thị gì | `preview` trong payload agent gửi | **Render model** do `approval-signer` dựng từ intent đã xác minh chữ ký |
| Ai ký approval | `ui` (Chainlit giữ khoá ES256) | **`approval-signer`** (service riêng, không egress), Chainlit không giữ khoá |
| Chữ ký ràng buộc | `sha256(args)` do agent/UI tự dựng | `intent_sha256` = băm payload intent do **MCP ký** |
| Ghi dữ liệu | `close_ticket(args, approval_token)` | `prepare_close_ticket(args)` rồi `commit_intent(intent_id, approval_token)` |
| TOCTOU | tuỳ chọn `expected_updated_at` trong args | `expected_updated_at` **nằm trong intent đã ký**, lệch → `conflict` |

## 1. Mô hình đe doạ

### 1.1 Giả định

| Chủ thể | Mức tin cậy | Ghi chú |
|---|---|---|
| Người dùng (human approver) | Tin cậy là người ra quyết định; có thể mệt mỏi/bị đánh lừa bằng nội dung hiển thị | Đo ở user study (mục 11) |
| **Agent + LLM** | **Không tin cậy hoàn toàn**: có thể bị prompt injection, bị chiếm tiến trình, hoặc bug | Giả định thiết kế cốt lõi của D1 |
| Nội dung tài liệu/ticket/dữ liệu | Không tin cậy (injection lưu trữ) | Spotlighting ở `02` |
| tickets-mcp | Tin cậy (giữ khoá intent, đọc DB, thực thi ghi) | Mỗi MCP có cặp khoá riêng |
| approval-signer | Tin cậy (giữ khoá approval) | Mã nguồn ≤ 300 dòng để review được |
| **UI backend (Chainlit, sau này BFF)** | Tin cậy một phần: **bị chiếm = rủi ro còn lại** (1.3) | Giảm thiểu ở M6 và step-up (mục 12) |
| Keycloak, Postgres, Redis | Tin cậy (hạ tầng); Redis `state` có ACL theo user | |

### 1.2 Các mối đe doạ và biện pháp

| ID | Mối đe doạ | Kịch bản | Biện pháp D1 | Còn lại |
|---|---|---|---|---|
| T1 | Agent bị lừa/chiếm đề xuất thao tác khác ý người dùng | Người dùng nói "đóng TCK-000123"; agent gửi `close TCK-000999` kèm lời giải thích đẹp | Thẻ chỉ lấy từ intent do MCP tính; mã ticket, `before`, `after` hiển thị đúng đối tượng sẽ bị ghi | Người dùng phải đọc thẻ (user study) |
| T2 | Agent tráo args giữa lúc duyệt và lúc ghi | Duyệt `resolution=A`, gọi ghi với `resolution=B` | `commit_intent` **không nhận args**; MCP thực thi `args_canonical` lấy từ intent đã lưu; approval gắn `intent_sha256` | — |
| T3 | Agent tự tạo "intent" giả | Dựng JWS giả để xin signer ký | Signer chỉ ký intent có chữ ký ES256 của MCP (khoá công khai mount sẵn, theo `iss`+`kid`); agent không có khoá intent | — |
| T4 | Agent tự xin approval | Agent gọi `POST /v1/approvals` bằng token user nó đang cầm | **Đã quyết D13:** token user gửi agent chỉ có `aud=agent-service`; UI backend tự token-exchange (RFC 8693) sang `aud=approval-signer`, giữ server-side theo `session_id` (TTL ≤ 5 phút), không bao giờ gửi cho agent/trình duyệt; Keycloak chỉ cho `chat-ui`/`bff` exchange tới `approval-signer`, `agent-service` bị từ chối; signer kiểm `aud`, `azp ∈ {chat-ui, bff}`, `sub == intent.sub` | Residual F30 (UI backend bị chiếm) |
| T5 | Replay approval/intent | Dùng lại approval, hoặc commit hai lần song song | `jti` `SET NX` (`mcp:tickets:jti:*`), `intent.status` pending→committed, chỉ mục `UNIQUE(intent_id)` ở DB độc lập Redis | — |
| T6 | TOCTOU | Ticket bị người khác sửa giữa prepare và commit | `expected_updated_at` trong intent; UPDATE có điều kiện, 0 dòng → `conflict` | Người dùng phải prepare lại |
| T7 | Giả danh người dùng | Approval của user A dùng cho phiên user B | Approval `sub` = `intent.sub` = `caller.sub` (3 điểm kiểm: signer, commit, DB `actor_sub`) | — |
| T8 | Confused-deputy theo clearance | Agent đọc doc mật (clearance 3) rồi ghi nội dung vào ticket mà người clearance thấp đọc được | Taint D8: `risk_flags:["possible_downgrade"]`, UI cảnh báo đỏ; chính sách `warn|block` | Taint thô (mục 7.5) |
| T9 | Sửa dữ liệu sau khi duyệt nhờ "edit" | UI cho sửa rồi ký args do UI dựng | Nhánh edit **gọi lại `prepare_*`**; không có đường ký args do UI/agent dựng | — |
| T10 | Hạ tầng chéo | Khoá approval lộ qua Chainlit | Khoá chỉ ở container `approval-signer`; Chainlit không có khoá | Chiếm signer |
| T11 | **UI backend bị chiếm** | Kẻ tấn công điều khiển tiến trình Chainlit | Không chặn được việc xin chữ ký cho **intent của chính user đang đăng nhập** (token của user nằm ở UI) | **Rủi ro còn lại** (1.3) |
| T12 | Mệt mỏi/duyệt phản xạ | Người dùng bấm Duyệt không đọc | Thẻ ngắn, diff rõ, cờ rủi ro; đo `approval_latency`; step-up cho thao tác rủi ro cao (mục 12) | Hành vi con người |

### 1.3 Rủi ro còn lại (ghi rõ, không che giấu)

1. **UI backend bị chiếm** có thể hiển thị thẻ giả cho người dùng *và* xin signer ký approval cho intent thật của user đó (vì nó cầm token của user). Intent của người **khác** thì không (cần token của họ). Giảm thiểu: M6 tách BFF tối giản (bề mặt nhỏ, không chạy code LLM/markdown phức tạp); step-up WebAuthn/CIBA (mục 12) làm "bằng chứng có mặt của người" độc lập với UI backend.
2. **Người dùng duyệt nhầm** dù thẻ đúng (fatigue). Đo bằng user study và `approval_latency_seconds`.
3. **Taint thô**: có thể over-flag (người dùng chỉ đọc 1 doc mật rồi ghi ticket vô hại trong 30 phút).
4. **Chiếm tickets-mcp** = chiếm cả khoá intent: ngoài phạm vi; giảm bằng tách khoá intent theo MCP, đọc-ghi DB bằng role tối thiểu (`02`).

## 2. Luồng cũ và lỗ hổng R01

Luồng v1.1 (đã bỏ): agent dựng `pending_action{tool,args,preview}` → UI nhận interrupt, hiển thị `preview`, **tự băm `args` nó nhận được** và ký ES256 `{tool, args_sha256, sub, jti, exp}` → agent gọi `close_ticket(args, approval_token)`; MCP kiểm `sha256(args)` khớp.

Lỗ hổng (review R01/R05):

| # | Lỗ hổng | Hệ quả |
|---|---|---|
| L1 | `preview` và `args` đều do agent cung cấp; chữ ký chỉ chứng minh "UI ký đúng cái agent đưa" | Agent bị chiếm đưa preview đẹp + args độc; người dùng duyệt "đóng TCK-1", MCP ghi "đóng TCK-9" miễn hai thứ trong payload của agent khớp hash |
| L2 | Chữ ký ràng buộc **đầu vào** (args), không ràng buộc **hiệu ứng** (before/after, đối tượng thực) | Không phát hiện lệch giữa mô tả và tác động; TOCTOU chỉ tuỳ chọn |
| L3 | Chainlit giữ khoá ES256 và là bên ký | Bề mặt tấn công UI (markdown, plugin) = bề mặt đánh cắp khoá |
| L4 | `decode_unverified` trên access token; `SESSION_TOKENS[sub]` khoá theo `sub` | Hai tab/phiên của cùng user dùng chung/ghi đè token; phiên chéo (R05) |
| L5 | Nhánh "Sửa" ký lại trên args do UI dựng | UI/agent tự quyết nội dung được ký |
| L6 | Một người dùng ký được cho `thread_id` bất kỳ UI nhận | Phụ thuộc UI kiểm tra |

v1.2 loại bỏ L1–L6 bằng nguyên tắc: *nội dung hiển thị và nội dung ký đều bắt nguồn từ cùng một artefact do bên tin cậy (MCP) tính và ký; bên ký approval (signer) không nhận dữ liệu từ agent*.

## 3. Luồng D1 chi tiết

### 3.1 Các bước (chuẩn)

1. **Prepare.** Agent gọi `prepare_<op>(args)` (scope `tickets:write`, không đổi dữ liệu). tickets-mcp: validate, phân quyền (`TicketPolicy`), đọc DB, chuẩn hoá args (điền mặc định), tính `before/after`, đọc taint (7), dựng `risk_flags`, ký JWS bằng **khoá intent**, lưu `mcp:tickets:intent:{intent_id}` (HASH, TTL 330s = `exp-iat` 300 + 30s ân hạn để trả `intent_expired` rõ ràng), trả `{intent_id, intent_jws, expires_at}` cho agent.
2. **Interrupt.** Agent `interrupt({kind:"write_approval", intent_jws, intent_id})`. Agent **không** dựng preview, không đọc nội dung intent để quyết định hiển thị.
3. **Verify/render.** UI backend gọi `POST signer /v1/intents/verify` kèm token riêng của user. Signer xác minh chữ ký MCP + `exp` + `sub`, trả **render model**. UI chỉ vẽ render model.
4. **Approve.** Người dùng bấm Duyệt → UI gọi `POST /v1/approvals {intent_jws}` → signer kiểm lại, ký **approval token** (hiệu lực 120s).
5. **Resume.** UI `Command(resume={decision:"approve", approval_token})`. Agent gọi `commit_intent(intent_id, approval_token)`.
6. **Commit.** tickets-mcp kiểm approval (chữ ký, `aud`, `sub`, `intent_sha256`), tải intent từ Redis, so khớp, `SET NX jti`, thực thi `args_canonical` với `expected_updated_at` trong **một transaction** cùng `ticket_events` và `tool_audit` (D6), đặt `status=committed`.

### 3.2 Sequence diagram (luồng chính và các nhánh lỗi)

```mermaid
sequenceDiagram
  autonumber
  actor U as Người dùng
  participant UI as UI backend
  participant AG as agent
  participant TK as tickets-mcp
  participant RS as redis-state
  participant SG as approval-signer
  participant DB as Postgres tickets

  U->>UI: "Đóng TCK-000123, đã xử lý xong"
  UI->>UI: token exchange (D13): token user → aud=approval-signer, lưu server-side theo session_id (TTL ≤ 5 phút)
  UI->>AG: POST /threads/{id}/runs (chỉ token aud=agent-service)
  AG->>TK: prepare_close_ticket(code, resolution)
  TK->>DB: đọc ticket (RLS + TicketPolicy)
  TK->>RS: đọc mcp:taint:{sub}
  TK->>TK: tính intent, ký JWS ES256 (khoá intent)
  TK->>RS: HSET mcp:tickets:intent:{id} sha256 sub status=pending jws, EXPIRE 330
  TK-->>AG: intent_id, intent_jws, expires_at
  AG->>AG: interrupt(intent_jws) và checkpoint
  AG-->>UI: event interrupt {intent_id, intent_jws}
  UI->>SG: POST /v1/intents/verify (intent_jws, token signer aud=approval-signer, azp=chat-ui|bff)
  SG->>SG: verify JWKS, aud, azp ∈ {chat-ui, bff}, sub == intent.sub, chữ ký MCP, exp
  SG-->>UI: render model (before, after, risk_flags)
  UI-->>U: Thẻ từ render model [Duyệt] [Sửa] [Từ chối]

  alt Duyệt
    U->>UI: bấm Duyệt
    UI->>SG: POST /v1/approvals (intent_jws, token signer aud=approval-signer)
    SG->>SG: kiểm lại intent, sub, exp, ký approval ES256 (exp = iat + 120)
    SG-->>UI: approval_token
    UI->>AG: POST /resume {approve, approval_token}
    AG->>TK: commit_intent(intent_id, approval_token)
    TK->>TK: verify chữ ký approval, aud, sub = caller.sub
    TK->>RS: HGETALL intent, so sha256 = approval.intent_sha256, status = pending
    TK->>RS: SET mcp:tickets:jti:{jti} NX EX 180
    TK->>DB: BEGIN, UPDATE ... WHERE updated_at = expected
    TK->>DB: INSERT ticket_events, INSERT tool_audit, COMMIT
    TK->>RS: HSET intent status=committed
    TK-->>AG: ok, ticket, event_id
    AG-->>UI: done (completed)
  else Sửa
    U->>UI: nhập resolution mới
    UI->>AG: POST /resume {edit, args_patch}
    AG->>TK: prepare_close_ticket(args mới)
    TK-->>AG: intent MỚI (intent_id mới)
    AG->>AG: interrupt(intent_jws mới)
    AG-->>UI: event interrupt (vòng duyệt mới, quay lại bước verify)
  else Từ chối
    UI->>AG: POST /resume {reject, reason?}
    AG->>AG: không gọi commit, final_answer "đã huỷ"
  end
```

### 3.3 Các nhánh lỗi

```mermaid
sequenceDiagram
  autonumber
  participant UI as UI backend
  participant AG as agent
  participant TK as tickets-mcp
  participant RS as redis-state
  participant SG as approval-signer

  Note over UI,SG: Nhánh hết hạn
  UI->>SG: /v1/approvals (intent đã quá exp)
  SG-->>UI: 410 intent_expired
  UI-->>AG: resume {reject, reason: expired}
  Note right of AG: agent gọi lại prepare_* nếu người dùng muốn tiếp tục

  Note over UI,SG: Nhánh approval quá 120s
  AG->>TK: commit_intent(intent_id, approval cũ)
  TK-->>AG: approval_expired
  AG-->>UI: interrupt lại với CÙNG intent_jws nếu intent chưa hết hạn
  UI->>SG: /v1/approvals lần nữa (người dùng bấm Duyệt lại)

  Note over UI,SG: Nhánh conflict (TOCTOU)
  AG->>TK: commit_intent(intent_id, approval)
  TK->>TK: UPDATE ... WHERE updated_at = expected trả 0 dòng
  TK->>RS: HSET intent status=aborted
  TK-->>AG: conflict (details.reason = stale)
  AG-->>UI: thông báo ticket đã đổi, đề nghị prepare lại

  Note over UI,SG: Nhánh replay
  AG->>TK: commit_intent(intent_id, approval đã dùng)
  TK->>RS: SET mcp:tickets:jti NX trả false, hoặc intent.status = committed
  TK-->>AG: approval_replayed (details.already_applied = true, event_id)
```

### 3.4 Quy tắc trạng thái intent

```
pending --commit ok--> committed
pending --conflict (ticket đổi)--> aborted
pending --TTL--> (biến mất) => intent_not_found / intent_expired
```
`pending` + lỗi hạ tầng khi commit (DB/Redis) giữ nguyên `pending`; jti đã đốt nên người dùng nhận approval mới (jti mới) cho **cùng** intent nếu intent còn hạn. Chỉ mục `UNIQUE(ticket_events.intent_id)` bảo đảm không có hai lần ghi dù Redis mất trạng thái.

## 4. Định dạng artefact

### 4.1 Canonicalization và hash (dùng chung)

- `canonical_json(obj)`: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")`; mọi chuỗi chuẩn hoá **NFC** trước khi băm; chỉ chấp nhận string/int/bool/null/array/object (float → từ chối). Hàm duy nhất ở `acme_common/services/canonical.py` (thay mục 6.6 cũ của `02`); signer và MCP dùng chung, có test vector cố định.
- `args_canonical` = `canonical_json(args_chuẩn_hoá)` dạng **chuỗi** nhúng trong intent; chuẩn hoá do **MCP** làm (điền mặc định `priority`, `internal`...), không phải agent.
- `intent_sha256` = `hex(SHA-256(canonical_json(payload intent)))` (đúng contracts §4.1: JCS, khoá sắp xếp, không float). Bên kiểm giải mã payload JWS (sau khi verify chữ ký), canonical-hoá bằng **cùng hàm** `canonical_json` rồi băm; hai phía dùng chung một hàm và test vector nên không lệch serializer.

### 4.2 Intent JWS (compact, ES256)

Header: `{"alg":"ES256","kid":"tickets-intent-2026-10","typ":"acme-intent+jws"}`. `typ` riêng để không nhầm với approval; mỗi MCP một khoá và một `iss`.

```json
{
  "v": 1,
  "iss": "tickets-mcp",
  "aud": "approval-signer",
  "sub": "5f0c…",
  "iat": 1793174400,
  "exp": 1793174700,
  "intent_id": "0194c1e2-7b3a-7d10-9a4e-3f6f2f0b9c11",
  "op": "close_ticket",
  "target": {"ticket_code": "TCK-000123"},
  "before": {"status": "in_progress", "resolution": null, "title": "Máy in tầng 3 không in được"},
  "after":  {"status": "closed", "resolution": "Đã thay mực và cài lại driver máy in."},
  "expected_updated_at": "2026-10-28T08:12:44Z",
  "args_canonical": "{\"code\":\"TCK-000123\",\"resolution\":\"Đã thay mực và cài lại driver máy in.\"}",
  "risk": "medium",
  "risk_flags": ["destructive"]
}
```
Quy tắc: `exp = iat + INTENT_TTL_S` (mặc định 300); `sub` = `caller.sub` của lời gọi `prepare_*` (từ JWT đã verify, không phải tham số); `before/after` chỉ chứa trường thay đổi + định danh hiển thị; văn bản dài giữ nguyên trong `after` (người dùng phải thấy đúng cái sẽ ghi); kích thước ≤ 8 KiB (vượt → `invalid_argument`). `risk_flags` ∈ {`destructive`, `internal_comment`, `priority_urgent`, `possible_downgrade`, `taint_unknown`}.

Lưu Redis: `mcp:tickets:intent:{intent_id}` HASH `{sha256, sub, status, exp, op, ticket_code, jws}`.

### 4.3 Approval token (JWT ES256)

Header: `{"alg":"ES256","kid":"approval-2026-10","typ":"acme-approval+jwt"}`.

```json
{
  "iss": "acme-approval",
  "aud": "tickets-mcp",
  "sub": "5f0c…",
  "intent_id": "0194c1e2-7b3a-7d10-9a4e-3f6f2f0b9c11",
  "intent_sha256": "9b1e…(64 hex)",
  "jti": "e7b2…",
  "iat": 1793174460,
  "exp": 1793174580
}
```
`aud` lấy từ `intent.iss` (signer ánh xạ `iss → aud`), nên approval chỉ dùng được ở MCP đã phát intent. Khi bật step-up, thêm `acr`/`amr` (mục 12).

### 4.4 Kiểm tra ở `commit_intent` (thay bảng 6.7 cũ của `02`)

| # | Kiểm tra | Lỗi |
|---|---|---|
| 1 | `approval_token` có mặt | `approval_required` |
| 2 | `alg==ES256`, `typ`, `kid` ∈ tập khoá approval tin cậy | `approval_invalid` |
| 3 | Chữ ký, `iss=="acme-approval"`, `aud` chứa `tickets-mcp` | `approval_invalid` |
| 4 | `exp>now`, `exp-iat<=120`, `iat<=now+5` | `approval_expired` / `approval_invalid` |
| 5 | `sub == caller.sub` | `approval_mismatch` |
| 6 | `intent_id` ở tham số == claim; Redis có intent (`HGETALL`) | `intent_not_found` |
| 7 | `now <= intent.exp` | `intent_expired` |
| 8 | `intent.sub == caller.sub`; `intent.sha256 == approval.intent_sha256` (so sánh hằng thời gian); băm lại `jws` đã lưu cũng khớp | `intent_mismatch` |
| 9 | `intent.status == pending` (đã `committed` → `approval_replayed` + `already_applied`) | `approval_replayed` / `conflict` |
| 10 | `SET mcp:tickets:jti:{jti} NX EX 180` | `approval_replayed` |
| 11 | Phân quyền lại với principal hiện tại (`can_view`, `can_modify`, state machine) | `not_found` / `forbidden` / `conflict` |
| 12 | Thực thi trong 1 transaction, `WHERE updated_at=expected_updated_at` | `conflict` |
| 13 | Redis lỗi | `upstream_unavailable` (fail-closed) |

Thứ tự: bước 10 sau mọi kiểm rẻ, trước khi ghi; kiểm quyền (11) trước `SET NX` khi có thể để không đốt jti vì lỗi đoán trước (giữ nguyên tinh thần v1.1).

## 5. Service `approval-signer`

### 5.1 Vị trí và nguyên tắc

- Container riêng (`packages/approval_signer`), mạng `core` only, **không egress**, cổng **8310**, chỉ phụ thuộc `fastapi`, `pyjwt`, `cryptography`, `acme_common`; tổng ≤ ~300 dòng (CI `wc -l` kiểm tra). JWKS Keycloak lấy qua `TokenVerifier` dùng lại từ `acme_common` (HTTP nội bộ tới Keycloak trong mạng `core`).
- **Không Redis, không DB** (D12): stateless. Đơn-dùng của approval do tickets-mcp bảo đảm (jti). Rate limit trong bộ nhớ (theo `sub`, mặc định 30 approval/giờ) chỉ là lớp phụ.
- Keycloak (D13): client `approval-signer` (bearer-only, audience). **Không** có audience mapper `approval-signer` trên `chat-ui`: token đăng nhập chỉ có `aud=agent-service`. UI backend (Chainlit; `bff` ở M6) exchange `subject_token=<token user>` → `audience=approval-signer`, giữ trong session server-side (khoá `session_id`, TTL ≤ 5 phút, không cache sang session khác). Quyền exchange tới `approval-signer` chỉ cấp cho `chat-ui` và `bff`; `agent-service` chỉ được exchange tới `docs-mcp|tickets-mcp|analytics-mcp`. Cả `/v1/intents/verify` và `/v1/approvals` đòi token này; signer verify JWKS, `iss`, `exp`, `aud ∋ approval-signer`, `azp ∈ SIGNER_ALLOWED_AZP = {chat-ui, bff}` và `sub == intent.sub`, ngược lại `403 forbidden`.
- **Rủi ro T4 (đã quyết D13):** agent bị chiếm không có token nào mang `aud=approval-signer` và không exchange được, nên không tự xin approval. Phần còn lại là UI backend bị chiếm (F30), giảm bằng step-up (mục 12).

### 5.2 Ports (ABC, theo contracts §9)

| Port | Method | Adapter v1 | Ghi chú |
|---|---|---|---|
| `IntentVerifier` | `verify(intent_jws, user_principal) -> RenderModel` (ném `intent_expired`, `intent_mismatch`) | `es256_jws.py`: thư mục `INTENT_PUBLIC_KEYS_DIR/<kid>.pub` | `iss` cố định `tickets-mcp`; từ chối `alg` ≠ ES256, `typ` sai, `aud` ≠ `approval-signer`, `sub` ≠ user |
| `ApprovalSigner` | `sign(intent, principal) -> ApprovalToken` | `es256_file.py` (khoá PEM mount, `APPROVAL_SIGNER_KEY_ID`) | Thêm `kms.py` sau, không đổi service |
| `TokenVerifier` | `verify(token, audience) -> Principal` | `oidc_jwks` (dùng lại `acme_common`) | Kiểm `azp ∈ SIGNER_ALLOWED_AZP` và `aud` không chứa `agent-service`/`llm-gateway` |
| `Clock` | `now() -> datetime`, `monotonic() -> float` | `system.py`; `FakeClock` cho test | Test `exp`, ân hạn, skew |

Service `services/approval.py` chỉ phụ thuộc bốn port này. Factory registry dict + lazy import. Không bọc FastAPI/PyJWT thành port nào khác.

### 5.3 Endpoint

| Endpoint | Auth | Vai trò |
|---|---|---|
| `POST /v1/intents/verify` | Bearer user token (`aud=approval-signer`) | Xác minh intent, trả render model; **không** ký |
| `POST /v1/approvals` | như trên | Xác minh lại intent rồi ký approval |
| `GET /healthz` | không | Liveness |
| `GET /metrics` | `METRICS_TOKEN` | Prometheus |

`POST /v1/intents/verify` — request `{"intent_jws": "<compact>"}`. Response 200:

```json
{
  "intent_id": "0194c1e2-…", "op": "close_ticket",
  "target": {"ticket_code": "TCK-000123", "title": "Máy in tầng 3 không in được"},
  "before": {"status": "in_progress", "resolution": null},
  "after":  {"status": "closed", "resolution": "Đã thay mực và cài lại driver máy in."},
  "risk_flags": ["destructive"],
  "expires_at": "2026-10-28T08:20:00Z",
  "intent_sha256": "9b1e…",
  "display": {
    "title": "Đóng ticket TCK-000123", "risk": "medium",
    "diff": [
      {"field": "status", "before": "in_progress", "after": "closed"},
      {"field": "resolution", "before": null, "after": "Đã thay mực và cài lại driver máy in."}
    ]
  }
}
```
Sáu trường đầu (`intent_id, op, target, before, after, risk_flags, expires_at`) là render model theo contracts §4.1; `intent_sha256` và `display` là phần bổ sung (additive). Toàn bộ do **signer** dựng bằng mẫu cố định theo `op` (bảng `op → title/diff fields`), chỉ từ claims đã verify; mọi chuỗi là văn bản thuần (UI phải escape, không render HTML/markdown/ảnh). Lỗi (mã theo contracts): `401 unauthorized`; `403 forbidden` (azp/aud sai); `410 intent_expired`; `422 intent_mismatch` (chữ ký/`typ`/`kid`/`iss`/`aud` sai, hoặc `intent.sub ≠ user.sub`; `details.reason` ∈ `format|alg|typ|kid|iss|aud|signature|sub`); `422 invalid_argument` (JWS sai định dạng).

`POST /v1/approvals` — request `{"intent_jws": "…"}`. Response 200 `{"approval_token":"…","jti":"…","expires_at":"…"}`. Lỗi như trên + `429 rate_limited`. Signer **kiểm lại toàn bộ** (không tin lần verify trước).

### 5.4 Khung mã (minh hoạ, ~90 dòng lõi)

```python
# approval_signer/services/approval.py  (chỉ phụ thuộc ports)
class ApprovalService:
    def __init__(self, intents: IntentVerifier, signer: ApprovalSigner, clock: Clock): ...

    def render(self, jws: str, user: Principal) -> RenderModel:
        # chữ ký, typ, aud, exp, sub == user.sub (ném intent_mismatch / intent_expired)
        return self.intents.verify(jws, user)

    def approve(self, jws: str, user: Principal) -> ApprovalToken:
        intent = self.intents.verify_intent(jws, user)   # verify lại toàn bộ, không tin lần render
        # signer dựng claims cố định: iss=acme-approval, aud=tickets-mcp, sub=user.sub,
        # intent_id, intent_sha256, jti=uuid4, iat=clock.now(), exp=iat+APPROVAL_TTL_S
        return self.signer.sign(intent, user)
```
`intent_sha256 = sha256(canonical_json(payload intent))` (contracts §4.1), tính từ payload đã verify chứ không từ chuỗi do client gửi. Handler FastAPI chỉ: lấy Bearer → `TokenVerifier` → gọi service → map lỗi sang mã HTTP (thông điệp lỗi chung, không lộ claim).

### 5.5 Cấu hình và quản lý khoá

```
SIGNER_PORT=8310
KEYCLOAK_ISSUER=http://keycloak.acme.local:8080/realms/acme
SIGNER_AUDIENCE=approval-signer          SIGNER_ALLOWED_AZP=chat-ui,bff
INTENT_PUBLIC_KEYS_DIR=/run/keys/intent  # <kid>.pub, nhiều kid cùng lúc
APPROVAL_SIGNER_PRIVATE_KEY_PATH=/run/secrets/approval_signing_key   APPROVAL_SIGNER_KEY_ID=approval-2026-10
APPROVAL_TTL_S=120
SIGNER_RL_PER_HOUR=30    METRICS_TOKEN=…
# Ánh xạ iss intent -> aud approval là hằng trong mã: tickets-mcp -> tickets-mcp
```

| Khoá | Giữ ở | Công khai ở | Thuật toán |
|---|---|---|---|
| Intent (mỗi MCP một cặp) | tickets-mcp (Docker secret) | approval-signer (thư mục `<iss>/<kid>.pub`) | ES256 (P-256) |
| Approval | approval-signer (Docker secret) | tickets-mcp (`APPROVAL_PUBLIC_KEY_PATH`, thư mục/tệp chứa nhiều `kid`) | ES256 |

**Xoay khoá** (cả hai loại, không downtime): (1) sinh cặp mới với `kid` mới; (2) phát **khoá công khai mới** cho bên verify trước (thư mục chứa nhiều `kid`); (3) đổi `*_KID` ở bên ký, khởi động lại; (4) giữ khoá công khai cũ ≥ **15 phút** (≥ intent 300s + approval 120s + dư) rồi xoá; (5) ghi sự kiện vào audit. Khoá bị lộ: bỏ ngay `kid` khỏi tập tin cậy (fail-closed, các intent/approval đang bay chết; người dùng làm lại). Header `kid` lạ → từ chối, không fetch từ mạng.

Metrics: `signer_verify_total{result}`, `signer_approval_total{result}`, `signer_approval_latency_seconds` (từ `iat` intent đến lúc ký, đo độ chần chừ), `signer_key_age_days{kind}`.

## 6. Redis (redis-state): khoá và ACL

| Khoá | Kiểu | TTL | Ghi bởi | Đọc bởi | Nội dung |
|---|---|---|---|---|---|
| `mcp:tickets:intent:{intent_id}` | HASH | 330s | tickets (prepare, commit) | tickets | `sha256, sub, status, exp, op, ticket_code, jws` |
| `mcp:tickets:jti:{jti}` | STRING | 180s | tickets (SET NX) | tickets | `1` |
| `mcp:taint:{sub}` | STRING (int) | `MCP_TAINT_TTL_S`=1800s (làm mới mỗi lần ghi) | **docs** | tickets | max classification đã trả cho user |

ACL (bổ sung `users.acl`): `tickets`: `~mcp:rl:tickets-mcp:* ~mcp:tickets:intent:* ~mcp:tickets:jti:* %R~mcp:taint:*`; `docs`: `~mcp:rl:docs-mcp:* ~mcp:taint:*` (read+write vì script max, contracts §8); `signer`: không có user Redis. Prefix `{...}` tách rõ, không `KEYS`/`SCAN` cho tickets.

## 7. Taint chống confused-deputy theo clearance (D8)

### 7.1 Vấn đề

Người dùng clearance 3 hỏi agent về tài liệu mật; agent (hoặc injection trong tài liệu) ghi một phần nội dung vào comment/mô tả ticket mà người clearance 0–1 đọc được: rò rỉ hạ cấp, dù mọi lời gọi đều "đúng quyền" của người dùng.

### 7.2 Cơ chế

- **docs-mcp ghi** mỗi khi trả kết quả `search_documents`/`get_document`: `taint = max(taint_hiện_tại, max(classification các chunk trả về))` cho `mcp:taint:{sub}`, TTL 1800s, bằng script Lua nguyên tử (`+@scripting`). Ghi phía server; agent không đọc/ghi được khoá này.
- **tickets-mcp đọc** trong `prepare_*` (ghi nội dung tự do: `create`, `add_comment`, `update_status` có `reason`, `close` có `resolution`): so với `audience_floor(ticket)` = clearance tối thiểu của những người đọc được ticket đích.
- Quy tắc: nếu `taint > audience_floor` → thêm `possible_downgrade` vào `risk_flags` (và `risk=high`). Redis lỗi/không có khoá: coi như **không có taint** nhưng gắn `taint_unknown` khi Redis lỗi (khác với khoá không tồn tại = taint 0).
- `audience_floor(ticket)`: cột `tickets.classification` (mặc định 0, mới; xem mục 14); comment `internal=true` dùng `max(classification, INTERNAL_FLOOR)` (cấu hình, mặc định 1).

### 7.3 Chính sách

`TAINT_POLICY=warn|block` (cấu hình tickets-mcp). `warn`: intent có cờ, signer render cảnh báo đỏ ("Nội dung có thể xuất phát từ tài liệu mật mức N, ticket này người mức M đọc được"), người dùng quyết định. `block`: `prepare_*` trả lỗi `forbidden` với `details.reason="possible_downgrade"`, không tạo intent. Mặc định `warn`; khuyến nghị `block` cho ticket `classification=0` khi taint ≥ 2.

### 7.4 Kiểm thử

Xem F19–F21 (mục 9). Test đơn vị: bảng (taint × floor × policy × op).

### 7.5 Giới hạn

Per-user chứ không per-thread (over-flag); chỉ docs-mcp tạo taint (dữ liệu analytics/ticket phòng khác chưa tính; hướng mở rộng); không phân tích nội dung thực sự được chép. Đây là tín hiệu cho **con người**, không phải bằng chứng rò rỉ.

## 8. Thay đổi giao diện công cụ tickets-mcp (tóm tắt, schema ở `02` mục 6.3)

| Cũ (bỏ) | Mới |
|---|---|
| `create_ticket`, `add_comment`, `update_status`, `close_ticket` (nhận `approval_token`) | `prepare_create_ticket`, `prepare_add_comment`, `prepare_update_status`, `prepare_close_ticket` (không đổi dữ liệu) + `commit_intent(intent_id, approval_token)` |
| Agent giữ `args` | Agent chỉ giữ `intent_id` + `intent_jws` (mờ đục) |
| `propose_*` giả phía agent | Gọi thẳng `prepare_*` (tool thật, scope `tickets:write`) |

Token `tickets:write` chỉ cấp cho `prepare_*`/`commit_intent`; vẫn không cache (`03` mục 6).

## 9. Bảng fault-injection (security regression, chạy CI, fail build khi hồi quy)

Harness: `MaliciousAgent` (fake) gọi thẳng MCP/signer với chuỗi lời gọi tuỳ ý, có token hợp lệ của người dùng giả lập và các khoá test; vị trí `tests_e2e/approval_security/`. Kết quả xuất `e4_fault_injection.json`. Mọi ca khẳng định thêm: **DB không đổi** và (nếu có từ chối) có đúng 1 bản ghi `tool_audit` với `decision=deny`.

| # | Tấn công | Kịch bản | Kỳ vọng |
|---|---|---|---|
| F01 | Đổi args sau duyệt | Duyệt intent A (`resolution=OK`); agent gọi `commit_intent` thêm tham số `args`/`resolution="xoá hết"` | `invalid_argument` (schema `additionalProperties:false`); thực thi đúng `args_canonical` nếu gửi hợp lệ |
| F02 | Đổi đối tượng: prepare ticket X nhưng xin duyệt rồi commit intent của ticket Y | Dùng approval của intent A cho `intent_id` B | `intent_mismatch` |
| F03 | Intent giả ký khoá khác | Agent tự ký JWS giả (khoá lạ) đưa UI/signer | Signer `422 intent_mismatch` (`details.reason=signature`); không có approval |
| F04 | Intent đúng khoá nhưng `kid` ngoài tập tin cậy | JWS ký bằng khoá docs-mcp, `iss=tickets-mcp` | `422 intent_mismatch` (`kid` không thuộc `INTENT_PUBLIC_KEYS_DIR`) |
| F05 | Replay `jti` | `commit_intent` lần 2 với cùng approval | `approval_replayed` (+`already_applied`); 1 dòng `ticket_events` |
| F06 | Commit song song | 2 `commit_intent` đồng thời | 1 thành công, 1 `approval_replayed`; 1 dòng ghi |
| F07 | Dùng approval của user khác | Token approval `sub=u_hr` do `u_cs` gọi | `approval_mismatch` |
| F08 | Xin ký intent của user khác | Token user `u_cs`, `intent.sub=u_hr` gửi signer | `422 intent_mismatch` (`reason=sub`) |
| F09 | Intent hết hạn (signer) | Gửi intent `exp` đã qua | `410 intent_expired` |
| F10 | Intent hết hạn (MCP) | Approval hợp lệ nhưng `now > intent.exp` | `intent_expired` |
| F11 | Approval hết hạn | Commit sau 121s | `approval_expired` |
| F12 | Approval sống > 120s | Approval giả `exp-iat=600` (khoá test) | `approval_invalid` |
| F13 | Thuật toán yếu | `alg=none`, `alg=HS256` ký bằng public key | `approval_invalid` |
| F14 | Khoá/`kid` lạ hoặc `aud` sai | Approval ký khoá lạ; `aud=docs-mcp` | `approval_invalid` |
| F15 | Sửa `intent_sha256` | Approval hợp lệ nhưng claim băm khác | `intent_mismatch` |
| F16 | Ticket đổi sau prepare | Người khác UPDATE ticket sau prepare | `conflict`; intent → `aborted` |
| F17 | Agent bỏ qua prepare | `commit_intent` với `intent_id` tự bịa (uuid ngẫu nhiên) | `intent_not_found` |
| F18 | Commit không có approval | `commit_intent(intent_id)` thiếu token | `approval_required` |
| F19 | Gọi tool ghi cũ | `tools/call close_ticket` | Lỗi tool không tồn tại (JSON-RPC) và pinning loại tool |
| F20 | Thiếu scope | Token chỉ `tickets:read` gọi `prepare_close_ticket` | 403 `insufficient_scope` |
| F21 | Tham số danh tính | `prepare_*` kèm `sub`/`user_id` | `invalid_argument` |
| F22 | Token agent xin approval (D13) | Agent dùng token của mình (`aud=agent-service`, azp=agent-service) gọi `/v1/approvals` | `401 unauthorized` / `403 forbidden` (aud/azp), không ký |
| F22b | Agent exchange tới signer (D13) | `agent-service` gọi token-exchange `audience=approval-signer` | Keycloak từ chối (403 `access_denied`/`invalid_client`); không có token |
| F23 | Intent Redis bị mất | Xoá key intent sau prepare | `intent_not_found`, fail-closed |
| F24 | Redis chết lúc commit | Dừng redis-state | `upstream_unavailable`, không ghi |
| F25 | Lỗi giữa transaction | Giả lập lỗi sau UPDATE, trước INSERT audit | Rollback toàn bộ: không đổi ticket, không event; intent vẫn `pending` |
| F26 | Taint downgrade (warn) | Đọc doc c3, `prepare_add_comment` lên ticket c0 | Intent có `possible_downgrade`, `risk=high` |
| F27 | Taint downgrade (block) | Như F26 với `TAINT_POLICY=block` | `forbidden` (`reason=possible_downgrade`), không tạo intent |
| F28 | Clock skew | Approval `iat` > now + 5s | `approval_invalid` |
| F29 | Intent đã committed, xin approval mới | Signer ký thêm cho cùng intent, commit | `approval_replayed` (`already_applied`) |
| F30 | **Residual (ghi nhận, kỳ vọng thành công)** | UI backend giả mạo xin approval cho intent của chính user đó | Thành công; chỉ ghi nhận để theo dõi, giảm bằng step-up (mục 12) |

Chỉ số báo cáo (E4-3): số ca bị từ chối đúng mã / tổng; 0 ca ghi lọt; F30 báo riêng. Đây là **kiểm thử thuộc tính bảo mật**, không phải thí nghiệm thống kê.

## 10. Kiểm thử và ablation

- Unit: `ApprovalService` với `FakeIntentVerifier`/`FakeApprovalSigner`/`FakeClock`; `TicketService.commit_intent` với `FakeReplayGuard`, `FakeIntentIssuer`, `FakeApprovalVerifier`; canonical test vector chung signer↔MCP.
- Adapter permissive (`ApprovalVerifier=permissive`) **chỉ** khi `ACME_ENV=eval` (D1), phục vụ ablation "tắt xác minh" (chứng minh các ca F02–F15 sẽ lọt nếu thiếu lớp).
- E4-1 (mô phỏng): tỉ lệ đề xuất độc hại tới được thẻ duyệt + tỉ lệ bị duyệt bởi approver "ngây thơ" (kịch bản duyệt mọi thẻ): dùng làm cận trên, đối chiếu với user study.

## 11. User study (D10, E4-2)

**Mục tiêu.** Kiểm chứng giả thuyết: thẻ **intent server-computed** (before/after, cờ rủi ro) làm giảm tỉ lệ duyệt nhầm so với thẻ **args thô** (JSON/biểu mẫu từ chính agent).

**Thiết kế.** Within-subject, 2 điều kiện, đối cân bằng thứ tự (Latin square). Người tham gia 8–12 (nhân viên văn phòng/IT, không bắt buộc kỹ thuật), pilot 2 người trước, loại khỏi phân tích.

| Điều kiện | Thẻ hiển thị |
|---|---|
| A (đối chứng) | Lời giải thích của agent + tham số thô (`code`, `resolution`, ...) như agent gửi (mô phỏng luồng v1.1) |
| B (đề xuất) | Render model của signer: tiêu đề, đối tượng thực (mã + tiêu đề ticket), diff before/after, cờ rủi ro |

**Kịch bản.** 24 thao tác mỗi người (12 mỗi điều kiện, thứ tự ngẫu nhiên): 50% hợp lệ, 50% độc hại/sai lệch được dàn dựng: mã ticket khác với yêu cầu, `resolution` bị đổi nghĩa, bình luận nội bộ bị đổi thành công khai, đóng ticket đã `resolved` bởi người khác, `possible_downgrade`, ticket tiêu đề giống nhau khác mã. Mỗi ca có "yêu cầu gốc" của người dùng (lời nhắn) để so. Người tham gia đóng vai chủ yêu cầu và quyết định Duyệt/Sửa/Từ chối.

**Chỉ số.** Chính: **tỉ lệ duyệt nhầm** (duyệt ca độc hại), Wilson 95% CI mỗi điều kiện, so cặp bằng McNemar / mô hình logistic hỗn hợp (hiệu ứng ngẫu nhiên theo người). Phụ: tỉ lệ từ chối nhầm (ca hợp lệ), thời gian quyết định, độ tự tin (Likert 1–5), SUS rút gọn, NASA-TLX rút gọn, bình luận định tính. Ghi cỡ mẫu nhỏ nên báo cả dữ liệu từng người, không chỉ p-value; giả thuyết và cách phân tích đăng ký trước khi thu thập.

**Đạo đức/đồng thuận.** Tình nguyện, có phiếu đồng thuận nêu rõ mục đích, rằng "một số đề xuất có thể sai/độc hại" (không đánh lừa về bản chất nghiên cứu), quyền rút lui bất kỳ lúc nào; dữ liệu giả, không dùng ticket/tài khoản thật; định danh được thay bằng mã người tham gia, không ghi hình khuôn mặt; ghi màn hình chỉ cục bộ, xoá sau phân tích; lưu dữ liệu ẩn danh tối đa 12 tháng; phỏng vấn kết thúc (debrief) giải thích ca nào độc hại; phê duyệt nội bộ theo quy định của tổ chức trước khi chạy; không dùng cấp dưới/đồng nghiệp trực tiếp của người nghiên cứu để tránh sức ép.

**Sản phẩm.** `eval/approval_study/`: kịch bản (JSON), ứng dụng thẻ hai điều kiện, script phân tích, báo cáo; số liệu công bố cùng seed/phiên bản.

## 12. Phương án nâng cao (tuỳ chọn): step-up WebAuthn / CIBA

Mục đích: thu hẹp rủi ro T11 (UI backend bị chiếm) và T12 cho thao tác `risk=high`/`possible_downgrade`/`destructive`.

- **WebAuthn.** `POST /v1/approvals` trả `401 step_up_required` với `challenge = intent_sha256` (base64url). Trình duyệt gọi `navigator.credentials.get` với challenge đó; UI gửi lại assertion; signer verify (khoá công khai đăng ký của user, lưu ở Keycloak/signer) và thêm `acr:"webauthn"`, `amr:["hwk"]` vào approval; tickets-mcp bắt buộc `acr` cho intent có cờ rủi ro cao. UI backend bị chiếm không có khoá phần cứng của người dùng nên không tự duyệt được.
- **CIBA (Keycloak backchannel).** Signer gọi Keycloak khởi tạo CIBA với `binding_message` = tóm tắt render ("Đóng TCK-000123"); người dùng xác nhận trên thiết bị khác; signer nhận kết quả rồi ký. Cần egress tới Keycloak nội bộ (cùng mạng `core`) và poll/ping callback.
- Ràng buộc nhất quán: bằng chứng step-up luôn gắn `intent_sha256`; không tái sử dụng.
- **[SPIKE]** hỗ trợ WebAuthn/CIBA ở Keycloak phiên bản chọn; luồng đăng ký khoá. Ngoài milestone v1.0 (mục "Tuỳ chọn sau v1.0" của D0).

## 13. Triển khai theo milestone

| Milestone | Nội dung |
|---|---|
| M1 | `approval-signer` + `prepare_close_ticket`/`commit_intent`; UI gọi signer; F01–F18 chạy CI |
| M3 | Đủ 4 `prepare_*`; taint docs→tickets (D8); F19–F30 |
| M5 | Security regression trong CI; user study |
| M6 | BFF tối giản thay Chainlit làm UI backend ký |
| Sau v1.0 | Step-up WebAuthn/CIBA |

## 14. Phụ thuộc contracts v1.2

Mục đã chốt bởi D13/D14: #1 (D13), #2 và #3 (D14); xoay khoá overlap 15 phút và TTL Redis intent 330 s = exp + 30 s (D14). Contracts v1.2 (`00-contracts.md` §4.1, §6, §8, §9.2) đã khớp với tài liệu này ở: định dạng intent/approval, `intent_sha256 = sha256(canonical_json(payload))`, render model, mã lỗi `intent_not_found|intent_expired|intent_mismatch`, `/v1/intents/verify` + `/v1/approvals` đều đòi access token user (aud `approval-signer`), ACL Redis cho `mcp:taint:*`, env `TAINT_POLICY|INTENT_TTL_S`, ports `IntentIssuer|IntentVerifier|ApprovalSigner|ApprovalVerifier|ReplayGuard|Clock`. Các điểm còn lệch hoặc cần xác nhận:

1. **Một access token cho hai audience (T4/F22/F30): đã quyết D13.** Bỏ audience mapper `approval-signer` trên `chat-ui`; UI backend token-exchange riêng, giữ server-side; signer kiểm `aud`, `azp ∈ {chat-ui, bff}`, `sub == intent.sub`. Contracts §8 do worker khác cập nhật theo D13.
2. DB tickets (chốt D14): `tickets.classification` mặc định `INTERNAL`; `ticket_events.intent_id uuid` (UNIQUE) + `intent_sha256 text` thay cho `args_sha256`; `tool_audit.intent_id` nullable; role `mcp_audit_w` chỉ INSERT. Env `INTERNAL_FLOOR` (mặc định 1).
3. **Chốt D14:** `IntentIssuer.issue(op, target, draft, ctx)`; `draft` là args đã chuẩn hoá. Ghi chú gốc: tickets-mcp cần nhận thêm bản nháp đã tính (`before/after/expected_updated_at`, đọc qua `TicketRepository.read_for_intent`). Đề xuất truyền qua tham số `draft` hoặc dựng trong adapter có repo; ghi nhận là lệch nhỏ so với chữ ký contracts.
4. Taint là mô-đun thường `acme_common/services/taint.py` dùng thẳng Redis client (không phải port, đúng §9 "không bọc Redis client"); test bằng fakeredis.
5. Mã HTTP của signer dùng mã lỗi contracts; nếu bật step-up thêm `step_up_required` (mục 12).
6. `canonical_json`/`intent_sha256` ở `acme_common/services/canonical.py` dùng chung.
