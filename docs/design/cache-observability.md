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
- Request chuẩn hoá gồm `messages` (kể cả lượt tool), `tools`, `tool_choice`, `temperature`, `max_tokens`. Không gồm request id.

Prompt hiện không chứa thời gian hay id biến đổi (đã kiểm `graph/nodes.py`), nên hai câu hỏi giống nhau cho cùng khoá. Phải giữ tính chất này, và có test để không ai vô tình thêm timestamp vào system prompt.

### Vì sao an toàn khi quyền đổi

Prompt chứa chunk đã qua RLS. Người bị thu hồi quyền sẽ truy xuất ra tập chunk khác, tức prompt khác, tức khoá khác. Tài liệu sửa nội dung cũng vậy. Do đó không cần cơ chế xoá cache theo tài liệu.

Exact cache an toàn vì câu trả lời chỉ là hàm của prompt (messages, tools, tham số, model): cùng đầu vào thì đầu ra đã được phép lộ cho đúng người đó. Phạm vi quyền trong khoá là **lớp phòng thủ thêm**, thừa về lý thuyết vì bằng chứng đã nằm trong prompt. ADR-007 vẫn giữ nó vì an toàn hơn và hit rate thấp đi là cái giá chấp nhận được. Mức thấp đi bao nhiêu chính là một nhánh đo của RQ4: `strict` so với `evidence-keyed`.

### Quy tắc

| Trường hợp | Xử lý |
|---|---|
| Request có `tools` hoặc lượt tool | Vẫn cache được (agent luôn gửi tools). Danh sách tools (sắp xếp ổn định), `tool_choice` và toàn bộ messages nằm trong chuỗi băm |
| Response có `tool_calls` | Không bao giờ ghi, nên hit không phát lại lời gọi tool. Thao tác ghi luôn cần tool_call (`prepare_*`) nên không bị cache. Chỉ ghi text thuần: `finish_reason=stop`, không tool_calls, nội dung không rỗng |
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

### Trạng thái triển khai

Đã làm (mặc định TẮT, `GW_CACHE_ADAPTER=off`; bật `redis` cùng `--profile cache`):

- Port `ResponseCache` (`ports/response_cache.py`), adapter `adapters/redis.py`, `FakeResponseCache`, factory registry `off|redis`, `services/cache_key.py` thuần.
- Khoá thực tế: `cache:v1:{ver}:{dept}:{clearance}:{roles}:{provider.model}:{sha256}`. So với thiết kế thêm `ver` (`GW_CACHE_INDEX_VERSION`, tăng khi nạp lại index) và đưa provider vào phần model. Digest băm cả phạm vi, model, messages và params nên dù phần literal có trùng cũng không chung entry. Giá trị ngoài allowlist `[A-Za-z0-9_.-]{1,64}` thì không cache. `response_format` không vào khoá vì gateway bỏ qua tham số này.
- Không cache (bypass): không có user token đã xác minh. Request có `tools`/`tool_choice`/lượt tool vẫn cache (tools và tool_choice vào băm). Không ghi: `finish_reason != stop`, có tool call, nội dung rỗng, lỗi provider, stream bị ngắt. Redis lỗi hoặc chậm quá `GW_CACHE_TIMEOUT_S` là miss.
- Cache nằm dưới bước kiểm chứng của agent nên không biết câu trả lời `refused`; câu đó vẫn bị kiểm chứng lại mỗi lần. Chưa có điều kiện theo taint của thread (thiết kế không yêu cầu).
- Hit: header `x-acme-cache: exact`, `usage_events.cache='exact'` không token, span `cache=exact`, metric `gateway_cache_lookups_total{result}` và `gateway_cache_stores_total{result}`. Stream hit phát lại bằng một chunk nội dung.
- `redis-cache`: `allkeys-lru`, không AOF/RDB, ACL `gwcache` chỉ `GET/SET` trên `cache:v1:*`, user `ops` chỉ đọc để quét canary.
- Harness RQ4: `python -m eval.cache run ...` rồi `report` (xem `eval/cache/__main__.py`). Hai chế độ `plain` và `agent` (phát lại hội thoại có tools và lượt tool cố định, đại diện lời gọi cuối của agent). Nhánh `evidence-keyed` chỉ là mô phỏng ngoại tuyến, runtime luôn `strict`.

Chưa làm: semantic cache (đúng thứ tự cắt của ADR-007), chất lượng RAG qua cache (cần LLM thật), số RQ4 với LLM thật.

### Kết quả RQ4 trên stack thật (02/11/2026)

Stack compose đầy đủ (gateway `GW_CACHE_ADAPTER=off` rồi `redis`, cùng image), 7 phiên của 6 user thật từ Keycloak (token aud=llm-gateway đổi như agent, 6 phạm vi khác nhau, `an.nguyen` có hai phiên cùng phạm vi), khoá API của agent. Mỗi ô n=40 request tuần tự, `temperature=0`, `max_tokens=64`; seed cố định nên cache-off và cache-on hỏi đúng cùng dãy. Lệnh: `python -m eval.cache users --out <file>` (token ngắn hạn 300 giây, sinh lại trước mỗi lượt, xoá file sau khi dùng), `run --mode plain|agent --label cache-off|cache-on --seed 11|21`, `report`.

**LLM là `mock-provider`, độ trễ cố định khoảng 1,29 giây mỗi lời gọi.** Vì vậy p50/p95 của miss và mức tiết kiệm độ trễ KHÔNG đại diện LLM thật; chỉ có ý nghĩa: (a) chi phí phụ của cache so với không cache, (b) độ trễ của đường hit (Redis + gateway).

| Chế độ | Lặp | Hit rate (off / on) | p50 ms (off / on) | p95 ms (off / on) | p50 hit / miss ms (on) | Token tính phí (off / on) | Thăm dò chéo / trúng |
|---|---|---|---|---|---|---|---|
| plain | 0% | 0 / 0,0% | 1286 / 1287 | 1289 / 1300 | - / 1287 | 2320 / 2320 | 4 / 0 |
| plain | 20% | 0 / 15,0% | 1286 / 1287 | 1292 / 1329 | 3 / 1287 | 2320 / 1972 | 6 / 0 |
| plain | 50% | 0 / 37,5% | 1286 / 1287 | 1287 / 1332 | 4 / 1287 | 2320 / 1450 | 2 / 0 |
| agent | 0% | 0 / 0,0% | 1286 / 1287 | 1293 / 1294 | - / 1287 | 5400 / 5400 | 7 / 0 |
| agent | 20% | 0 / 12,5% | 1286 / 1287 | 1288 / 1328 | 5 / 1287 | 5400 / 4725 | 3 / 0 |
| agent | 50% | 0 / 42,5% | 1286 / 1287 | 1289 / 1333 | 9 / 1289 | 5400 / 3105 | 6 / 0 |

- Mọi lặp hợp lệ (cùng phạm vi hỏi lại) đều trúng: 6/6, 15/15, 5/5, 17/17; hit rate thấp hơn mức lặp danh nghĩa chỉ vì lặp chỉ phát sinh khi user đã hỏi trước đó.
- 28 thăm dò chéo phạm vi (prompt chỉ phạm vi khác đã hỏi), trúng 0. Khoá có phạm vi nên hai phạm vi khác nhau không bao giờ chung entry.
- Chi phí phụ ở mức lặp 0%: p50 tăng khoảng 1 ms, token không đổi; p95 chênh trong khoảng sai số đo (n=40). Ở mức 20% và 50% p95 cao hơn khoảng 40 ms ở nhánh on, chưa rõ nguyên nhân (có thể do ghi Redis sau lời gọi hoặc nhiễu), cần n lớn hơn mới kết luận.
- Đường hit mất 3 đến 9 ms; token tính phí giảm đúng bằng hit rate (12,5% đến 42,5%).
- Cột `evidence-keyed*` trong báo cáo là mô phỏng ngoại tuyến: hit rate sẽ cao hơn strict ở mọi mức (vd plain 50%: 42,5% so với 37,5%; agent 50%: 57,5% so với 42,5%), cái giá an toàn là phần chênh này. Runtime luôn `strict`.
- Cỡ mẫu nhỏ (n=40 mỗi ô, một seed): số ở đây là chứng minh cơ chế và mốc chi phí, chưa phải ước lượng thống kê. Lượt đầu n=100 bị hỏng vì token hết hạn giữa chừng nên không dùng.

**Rò rỉ có cache.** `scripts/e2e-leak-check.sh` (16 user, ~61 truy vấn docs-mcp + 5 lượt agent mỗi user) chạy hai lần liên tiếp khi cache bật: lượt 1 và lượt 2 đều 0 rò rỉ cứng, 0 rò tiêu đề, 0 lỗi, mọi user có đối chứng dương. Metric `gateway_cache_lookups_total` (gateway mới khởi động trước lượt 1): sau lượt 1 miss=228, hit=0; sau lượt 2 miss=380, hit=76, tức lượt 2 có 76 hit trên 228 lookup. Chưa có hit nào bị rò vì mọi hit đều cùng phạm vi.

**Quét canary trong redis-cache** (`python -m eval.cache scan`, user ACL `ops` chỉ đọc, mật khẩu đọc trong container từ secret): 651 khoá, 0 sai dạng; với mỗi khoá, tài liệu trái quyền của phạm vi trong khoá được tính độc lập với RLS (hàm của `eval/e2e/leak_check.py`), quét doc_id, tiêu đề và vân tay trong giá trị: 0 dấu vết. Hạn chế: mock-provider không chép nội dung tài liệu vào câu trả lời nên đối chứng dương bằng 0 (không khoá nào chứa dấu vết cả tài liệu được phép); phép quét được kiểm bằng test đơn vị với dữ liệu giả có rò, chưa chứng minh được bằng LLM thật. Cần chạy lại với LLM thật.

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
