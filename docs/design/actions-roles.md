# A1: Hành động qua MCP và phân quyền theo vai trò

Thực hiện phần "Hành động" và "Phân quyền" của [ADR-007](../adr/ADR-007-actions-cache-observability.md). Luồng phê duyệt nền ở [approval.md](approval.md); ở đây chỉ ghi phần thêm mới.

## 1. Ma trận quyền

ADR-007 để dự thảo; bản dưới là chốt.

| Vai trò | Tạo ticket | Đóng ticket | Gửi nhóm phòng | Gửi nhóm toàn công ty |
|---|---|---|---|---|
| `employee` | Có | Ticket được giao | Không | Không |
| `team_lead` | Có | Ticket được giao | Có | Không |
| `dept_manager` | Có | Trong phòng | Có | Không |
| `management` | Có | Trong phòng | Có | Có |
| `admin`, `auditor` | Không | Không | Không | Không |

Ba điểm lệch với code hiện tại phải sửa cùng lúc:

1. **Quyền cộng dồn làm hỏng "admin không ghi".** `oanh.ly` có cả `employee` và `admin`, nên lấy hợp quyền thì admin vẫn ghi được. Quy tắc: `admin` và `auditor` là vai trò **chặn**, có mặt là mất mọi quyền ghi, bất kể vai trò khác.
2. **`can_modify` rộng hơn ma trận.** `services/policy.py` cho `admin` sửa mọi ticket và cho `team_lead` sửa trong phòng. Ma trận không cho cả hai.
3. **`management` không có `employee`.** `phuc.cao` chỉ có `management`, nên `can_view` hiện từ chối ticket trong phòng dù ma trận cho đóng.

Quyền đọc không đổi: `admin` vẫn xem ticket, chỉ mất quyền ghi.

### Thực thi

Ma trận đặt một chỗ, `acme_common/services/capabilities.py`:

```python
class Capability(StrEnum):
    CREATE_TICKET = "create_ticket"
    CLOSE_ASSIGNED = "close_assigned"
    CLOSE_IN_DEPT = "close_in_dept"
    REPORT_DEPT = "report_dept"
    REPORT_COMPANY = "report_company"

_WRITE_BLOCKING = frozenset({"admin", "auditor"})
ROLE_CAPS: dict[str, frozenset[Capability]] = {...}

def allows(roles: Iterable[str], cap: Capability) -> bool: ...
```

Ba lớp, lớp sau không tin lớp trước:

| Lớp | Việc | Vai trò |
|---|---|---|
| Agent | Ẩn tool theo vai trò | Tiện dùng, không phải bảo vệ |
| MCP server | `allows()` ở cả `prepare_*` **và** `commit_intent` | Bảo vệ chính; vai trò có thể đổi giữa hai bước |
| RLS | `tk_insert`, `tk_update` viết lại tương đương, bỏ nhánh `admin` | Chặn khi code có lỗi |

SQL không gọi được Python nên điều kiện RLS là bản viết tay. Vì vậy test tham số hoá **mọi ô** của ma trận, chạy qua cả `allows()` lẫn Postgres thật. Một ô lệch thì test đỏ. Không tìm cách sinh SQL từ ma trận, không đáng cho 5 quyền.

`tk_select` giữ nguyên nhánh `admin` (quyền đọc), thêm nhánh `management` trong phòng.

## 2. `prepare_create_ticket`

Dùng lại nguyên state machine của intent. Phần thêm:

- Tham số: `title`, `body`, `category`, `priority`, `assignee_dept`, `classification`. `category` và `priority` là enum khai báo ở server.
- Signer đã có render cho `create_ticket` trong `_OPS`. `editable_fields` của agent gồm `title`, `body`, `priority`.
- `code` cấp lúc commit, không cấp lúc prepare: intent bị từ chối thì không tốn mã.
- Audience tính bằng `acme.ticket_audience`, cùng công thức taint với đóng ticket. Tạo ticket từ thread đã đọc tài liệu mật hơn audience thì có cờ `possible_downgrade`.
- `UNIQUE(ticket_events.intent_id)` chống tạo trùng khi commit lặp, như đóng ticket.

## 3. `notify-mcp`

Server mới, profile `notify`. Tool:

| Tool | Việc |
|---|---|
| `list_report_channels` | Trả bí danh kênh mà caller được gửi |
| `prepare_send_group_report` | `channel`, `text`; trả intent chờ duyệt |
| `commit_intent` | Gửi tin sau khi có approval JWT |

Kênh khai báo ở server, agent không bao giờ thấy chat ID:

```yaml
channels:
  dept-engineering: { adapter: telegram, chat_ref: TG_CHAT_ENG, scope: dept, dept: engineering, max_class: 1 }
  company-all:      { adapter: telegram, chat_ref: TG_CHAT_ALL, scope: company, max_class: 0 }
```

Telegram, Slack, Zalo OA đều nằm ngoài hạ tầng công ty, nên `max_class` của kênh ngoài bị **giới hạn ≤ 1 lúc nạp cấu hình**. Khai cao hơn thì service không khởi động.

Kiểm ở cả prepare và commit, vì giữa hai bước thread có thể đọc thêm tài liệu mật:

- Caller có `REPORT_DEPT` và thuộc phòng của kênh, hoặc `REPORT_COMPANY`.
- `taint.max_class <= channel.max_class`, xét cả `thread` lẫn `recent`.
- `taint is None` (Redis lỗi) thì **từ chối**, không chỉ gắn cờ như ticket. Tin đã gửi không thu hồi được nên phải fail-closed.

Taint dùng chung `thread_id` nên notify-mcp đọc được taint do docs-mcp ghi. Điều này cần thêm quyền đọc khoá `mcp:taint:*` vào Redis ACL của notify-mcp.

### Tin được gửi

- Văn bản thuần, không `parse_mode`, tắt link preview, giới hạn 3500 ký tự.
- Chuỗi được ký chính là chuỗi được gửi, byte-by-byte. Người duyệt thấy đúng thứ sẽ đi ra.
- Có URL trong tin thì thêm risk flag `contains_url`. Đây là đường rò dữ liệu kinh điển của prompt injection (RQ3).

### Gửi tối đa một lần

Telegram không có khoá idempotent. Nếu timeout sau khi gửi request thì không biết tin đã đi chưa, retry có thể gửi đúp vào nhóm công ty.

```sql
report_deliveries(intent_id UNIQUE, channel, text_sha256, status, ...)
-- sending -> sent | unknown
```

Ghi `sending` trước khi gọi, không lưu nội dung, chỉ hash. Chỉ tự retry khi chắc chắn chưa gửi: lỗi kết nối trước khi request đi, hoặc 429 có `retry_after`. Timeout sau khi gửi thì ghi `unknown` và báo người dùng tự kiểm tra trong nhóm. Thà báo không chắc còn hơn gửi đúp.

### Port

```python
class MessageChannel(ABC):
    @abstractmethod
    async def send(self, chat_ref: str, text: str) -> DeliveryReceipt: ...
```

`telegram.py` và `fake.py` trong `adapters/`, chọn bằng registry. Test và eval dùng `fake`, đúng hệ quả ADR-007.

**Bot token nằm trong URL** của Bot API. Đó là chỗ dễ rò nhất của cả A1, vì `httpx` log URL ở mức INFO và OTel gắn URL vào span. Adapter phải:

- Tắt logger `httpx`/`httpcore` cho client này và không để instrumentation chạm vào client đó.
- Ném lỗi chỉ gồm `kind` và `status`, không kèm URL hay exception gốc.
- Có test canary: token giả đi qua mọi nhánh lỗi, không xuất hiện trong log, exception, span.

## 4. Đổi hạ tầng intent

Phần intent đang nằm trong `mcp_tickets` và chép một phần sang signer, trong khi notify-mcp cần y hệt.

- Chuyển `es256_jws`, `es256_jwt`, replay guard, port `IntentIssuer` sang `acme_common`. State machine commit tách khỏi `TicketService` thành một service chung nhận callback thực thi.
- Signer đang chỉ tin một `iss` (`intent_issuer_name`). Đổi thành danh sách, và **gắn khoá với issuer**: khoá công khai ở `INTENT_PUBLIC_KEYS_DIR/<iss>/<kid>.pem`. Nếu để chung một thư mục, `tickets-mcp` bị chiếm có thể ký intent mạo danh `notify-mcp` và gửi tin ra ngoài.
- Gắn op với issuer: `send_group_report` chỉ nhận từ `notify-mcp`. Thêm vào `_OPS` và `_AUD_BY_INTENT_ISS`.
- Keycloak: thêm client `notify-mcp` và scope `notify:write`.
- Compose: notify-mcp nằm trong mạng `egress`, các MCP khác không.

## 5. Agent

Thêm `report` agent: một file `AgentSpec` và một dòng trong `factory._AGENTS`, đọc từ docs, ghi qua `prepare_send_group_report`. `ticket` agent thêm op `create_ticket`.

Nội dung báo cáo đi qua kiểm chứng trích dẫn như câu trả lời thường. Có khẳng định không kiểm chứng được thì thêm risk flag `unverified_claims` lên thẻ duyệt, không tự sửa nội dung.

## 6. Eval hành động

`eval/actions/cases.jsonl`, chạy bằng một lệnh, dùng adapter `fake` và LLM thật.

| Số đo | Nghĩa |
|---|---|
| Tool accuracy | Chọn đúng tool |
| Args accuracy | Đúng tham số; so theo trường, không so chuỗi |
| Over-action rate | Tạo intent khi người dùng chỉ hỏi. Chỉ số quan trọng nhất |
| Deny correctness | Từ chối đúng theo ma trận |

Tấn công qua tài liệu độc là phần của R3, dùng lại bộ này.

## 7. Thứ tự làm

Mỗi bước một worker, merge xong mới giao bước sau.

1. Ma trận quyền: `capabilities.py`, sửa `policy.py`, RLS, test mọi ô. Chạy lại E2E đóng ticket.
2. `prepare_create_ticket`.
3. Chuyển hạ tầng intent sang `acme_common`, signer nhiều issuer. Không đổi hành vi.
4. notify-mcp với adapter `fake`, `report` agent.
5. Adapter Telegram, test canary, demo trong nhóm thử nghiệm.
6. Eval hành động. Đo RAM với profile `tickets` + `notify`.
