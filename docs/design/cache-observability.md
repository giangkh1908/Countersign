# Q1: Cache và quan sát

Thực hiện phần "Cache" và "Quan sát" của [ADR-007](../adr/ADR-007-actions-cache-observability.md). Làm quan sát trước: cần trace và metric để đo cache.

## 1. Exact cache

### Đặt ở đâu

Ở **gateway**, vì đây là điểm duy nhất mọi lời gọi LLM đi qua và gateway biết danh tính thật từ token. Cache nằm dưới bước kiểm chứng của agent, nên câu trả lời từ cache vẫn được kiểm chứng lại như câu trả lời mới.

### Khoá

```text
cache:v1:{dept}:{clearance}:{roles}:{model}:{sha256(request chuẩn hoá)}
```

- Phần phạm vi quyền ở dạng literal, lấy từ `X-Acme-User-Token` đã xác minh, không lấy từ header hay body do client gửi. Không có token người dùng thì **không dùng cache**.
- Giá trị phạm vi phải qua allowlist ký tự trước khi ghép, để dấu `:` trong dept không tạo được khoá trùng của phạm vi khác.
- Request chuẩn hoá gồm `messages`, `temperature`, `max_tokens`, `response_format`. Không gồm request id.

Prompt hiện không chứa thời gian hay id biến đổi (đã kiểm `graph/nodes.py`), nên hai câu hỏi giống nhau cho cùng khoá. Phải giữ tính chất này, và có test để không ai vô tình thêm timestamp vào system prompt.

### Vì sao an toàn khi quyền đổi

Prompt chứa chunk đã qua RLS. Người bị thu hồi quyền sẽ truy xuất ra tập chunk khác, tức prompt khác, tức khoá khác. Tài liệu sửa nội dung cũng vậy. Do đó không cần cơ chế xoá cache theo tài liệu.

Riêng lập luận này cho thấy phạm vi quyền trong khoá là **thừa về lý thuyết**: bằng chứng đã nằm trong prompt. ADR-007 vẫn giữ nó vì an toàn hơn và hit rate thấp đi là cái giá chấp nhận được. Mức thấp đi bao nhiêu chính là một nhánh đo của RQ4: `strict` so với `evidence-keyed`.

### Quy tắc

| Trường hợp | Xử lý |
|---|---|
| Request có `tools` | Không đọc, không ghi cache. Đây là cách thực thi "không cache thao tác ghi" |
| `finish_reason != stop` | Không ghi |
| Redis lỗi | Coi như miss, vẫn trả lời. Cache không được làm hỏng đường chính |
| Request stream | Trả lại nội dung đã lưu dưới dạng SSE, giữ đúng định dạng chunk |
| Hit | Header `x-acme-cache: exact`, `usage_events.cache = 'exact'`, chi phí 0 |

`usage_events.cache` đã có sẵn cột và CHECK, không cần đổi schema. Agent đã đọc `x-acme-cache`.

Redis cache chứa dữ liệu mật theo đúng phạm vi của người hỏi. Vì vậy: TTL 1 giờ, tắt persistence, `allkeys-lru`, ACL riêng chỉ cho gateway, và canary được quét trong Redis. Thêm lại service `redis-cache` ở bước này.

### Port

```python
class ResponseCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> CachedResponse | None: ...
    @abstractmethod
    async def put(self, key: str, value: CachedResponse, ttl_s: int) -> None: ...
```

CLAUDE.md không bọc Redis client, nhưng cache là năng lực phải nằm sau port: cần fake cho test và cho nhánh đo RQ4. Adapter: `redis.py`, `fake.py`. Logic dựng khoá nằm ở `services/cache_key.py`, thuần, test được mà không cần Redis.

### Đo RQ4

| Câu hỏi | Cách đo |
|---|---|
| Tiết kiệm | Hit rate, chi phí, p50/p95 latency có và không cache |
| Chất lượng | Bộ eval RAG chạy lại trên kết quả từ cache, so với không cache |
| Rò rỉ | Hai người khác phạm vi hỏi cùng câu; canary quét trong Redis và câu trả lời |
| Strict hay evidence-keyed | Hit rate hai nhánh; số vụ rò phải bằng 0 ở cả hai |

Hit rate phụ thuộc hoàn toàn vào tỉ lệ câu hỏi lặp, mà không có dữ liệu thật về tỉ lệ này. Vì vậy báo cáo ở ba mức lặp 0%, 20%, 50% và không đưa ra một con số "tiết kiệm x%" duy nhất. Mức 0% là để đo chi phí phụ của cache.

Semantic cache vẫn tắt. Chỉ làm nếu còn thời gian sau khi có số của exact cache, đúng thứ tự cắt của ADR-007.

## 2. Trace

### Chọn gì

- **Backend: Tempo**, chế độ một tiến trình, profile `obs`. Grafana đã có nên không thêm giao diện. Service gửi OTLP thẳng tới Tempo, không dựng collector.
- **SDK: OTel trực tiếp**, `opentelemetry-instrumentation-fastapi` cộng span viết tay.
- **Đổi so với ADR-007:** ADR định thử OpenLLMetry trước. Thư viện này mặc định ghi nội dung prompt vào span, ngược với yêu cầu trace không chứa nội dung. Muốn dùng phải luôn đặt `TRACELOOP_TRACE_CONTENT=false`, và một lần quên là rò. Span viết tay ở gateway là đủ vì gateway là điểm duy nhất gọi LLM.

### Ở đâu

`acme_common/telemetry.py`: `setup_telemetry(service_name)`, không làm gì khi `OTEL_EXPORTER_OTLP_ENDPOINT` trống. Stack mặc định không tốn thêm gì.

Client MCP của agent dùng `httpx2`, chưa rõ instrumentation của `httpx` có áp dụng được không. Nếu không, gọi `propagate.inject(headers)` ở một helper dùng chung. Kiểm tra việc này ở bước đầu của Q1, tiêu chí: một trace xuyên BFF → agent → gateway → MCP thấy được trong Tempo.

### Span

| Span | Thuộc tính |
|---|---|
| `retrieval` | `candidates`, `returned`, `reranked` |
| `verification` | `claims`, `verified`, `failed` |
| `gen_ai.chat` (gateway) | `gen_ai.request.model`, `gen_ai.usage.*`, `cache`, `finish_reason` |
| `tool.{name}` | `outcome` |

Chỉ có số đếm và nhãn. Danh sách thuộc tính được phép đặt ở một chỗ, và span processor bỏ mọi thuộc tính ngoài danh sách. Như vậy quên ở một span cũng không rò.

Exception mặc định được OTel ghi kèm message, mà message có thể chứa nội dung. Tắt `record_exception`, chỉ ghi kiểu exception.

## 3. Log và metric

- `acme_common/log.py` thêm `trace_id` lấy từ span hiện tại, cạnh `request_id` đã có.
- Hiện chỉ gateway có metric Prometheus. Thêm cho agent, docs-mcp: thời gian truy xuất, tỉ lệ kiểm chứng đạt. Label không chứa user hay nội dung.
- Dashboard Grafana provision từ file, một bảng RAG và một bảng cache.
- Gom log tập trung là mục cắt được theo ADR-007, chưa làm.

## 4. Quét canary

Repo chưa có bộ quét canary, phải viết mới ở `eval/canary/`. Gửi request chứa một chuỗi canary ngẫu nhiên, rồi quét ba nơi: log của mọi service, trace lấy từ Tempo API theo đúng `trace_id`, và giá trị trong Redis cache của phạm vi khác. Có canary là đỏ. Riêng Redis cache của chính phạm vi đó được phép chứa canary, vì đó là nội dung được cache.

## 5. Thứ tự làm

1. Telemetry dùng chung, một trace xuyên suốt, `trace_id` trong log, allowlist thuộc tính.
2. Quét canary trên trace.
3. Metric và dashboard.
4. Exact cache với `fake`, rồi Redis.
5. Chạy đo RQ4. Đo RAM với profile `obs`.
