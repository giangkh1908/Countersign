# 06 — Policy-sidecar: embedding, guard và NER nội bộ

> Phiên bản v1.2. Tài liệu mới theo `DECISIONS-v1.2.md` D2. Nguồn chân lý chung là `00-contracts.md` (v1.2); khi mâu thuẫn, `DECISIONS-v1.2.md` thắng. Gateway (`01-gateway.md`) chỉ là egress mỏng và gọi sidecar qua HTTP nội bộ.

## Mục lục
1. Mục đích và ranh giới
2. Cấu trúc module (Ports & Adapters)
3. API
4. Lỗi, giới hạn, batching
5. Runtime và model
6. `models.lock`, tải và kiểm tra toàn vẹn
7. Cấu hình, tài nguyên, sizing
8. Xác thực, mạng, bảo mật
9. Metrics, log, SLO
10. Kế hoạch test
11. Pilot guard tiếng Việt (R17)
12. Giấy phép
13. Phụ thuộc contracts

---

## 1. Mục đích và ranh giới

`policy-sidecar` là một service Python nhỏ, chạy CPU, gom ba tác vụ suy luận mà gateway không còn tự chạy:

| Endpoint | Tác vụ | Model / công cụ | Gọi bởi |
|---|---|---|---|
| `POST /v1/embed` | Vector hoá văn bản | bge-m3 (ONNX int8) | gateway (semantic cache, `/v1/embeddings`, alias `acme-embed`); docs-mcp ingest đi **qua gateway**, không gọi thẳng |
| `POST /v1/guard` | Chấm điểm prompt injection | Prompt Guard 2 (ONNX) | gateway stage `guard` |
| `POST /v1/pii/ner` | NER tên người tiếng Việt | underthesea CRF | gateway stage `pii` (tuỳ chọn theo phòng ban) |

Lý do tách (D2): gateway giữ vai trò egress mỏng (RAM thấp, ít dependency, supply chain gọn); phần nặng CPU và phụ thuộc native (`onnxruntime`, `tokenizers`, `underthesea`) bị cô lập trong một process có thể scale, đo và khoá riêng.

Ranh giới:
- Sidecar **không** có API key của provider, **không** có egress ra Internet, **không** truy cập Postgres/Redis. Nó là hàm thuần: nhận văn bản, trả số/span.
- Sidecar **không lưu** và **không log** nội dung. Chỉ có bộ nhớ đệm LRU điểm guard theo `sha256(window)` trong RAM.
- Regex PII tiếng Việt (CCCD, SĐT, STK, MST, email, biển số) **ở lại gateway** (`regex_vi`); sidecar chỉ cung cấp NER cho PERSON.
- Sidecar không ra quyết định chặn/cho qua: chỉ trả điểm; chính sách `fail_open|fail_closed`, ngưỡng và hành động nằm ở gateway (`01` mục 1.8, 9).
- Chỉ nằm trong mạng `core`, cổng `8010`.

Đây là mô-đun triển khai bắt buộc khi bật bất kỳ stage nào cần model. Khi tắt cả `cache.semantic`, `guard` và NER, hệ thống chạy được không cần sidecar.

---

## 2. Cấu trúc module (Ports & Adapters)

Theo `00-contracts.md` §9. Package `packages/policy_sidecar`. Port dùng chung nằm ở `packages/common/ports` (`Embedder`, `InjectionGuard`, `PiiDetector`); sidecar cung cấp **adapter phía server** cho các port đó, gateway cung cấp adapter phía client (`sidecar_http`, `sidecar_ner`).

```
packages/policy_sidecar/
  src/policy_sidecar/
    main.py               # tạo FastAPI app, lifespan: verify models.lock -> nạp model -> ready
    settings.py           # pydantic-settings: SIDECAR_*; chỉ file này đọc env
    errors.py             # SidecarError + mã lỗi (mục 4)
    auth.py               # bearer SIDECAR_TOKEN (compare_digest), METRICS_TOKEN
    adapters/
      embedder_bge_m3_onnx.py        # Embedder   : "bge_m3_onnx"
      guard_prompt_guard2_onnx.py    # InjectionGuard : "prompt_guard2_onnx"
      guard_noop.py                  # InjectionGuard : "noop" (trả 0.0)
      pii_ner_underthesea.py         # PiiDetector    : "underthesea_ner" (process pool)
      pii_ner_noop.py                # PiiDetector    : "noop"
      ort_session.py                 # hạ tầng dùng chung: tạo InferenceSession (thread, graph opt)
    factory.py            # registry dict + lazy import: make_embedder/make_guard/make_ner(settings)
    services/
      models_lock.py      # đọc models.lock, verify sha256, trả đường dẫn đã xác thực
      windowing.py        # chia cửa sổ 512 token cho guard
      batching.py         # gom micro-batch, semaphore, deadline
      guard_cache.py      # LRU 20k theo sha256 cửa sổ
    api/
      schemas.py          # Pydantic request/response (extra="forbid")
      embed.py  guard.py  pii_ner.py  health.py
    observability.py      # metric sidecar_*, không label nhạy cảm
  scripts/
    fetch_models.py       # tải model theo models.lock (mục 6.3) - chạy ở CI/bước build, không ở runtime
    lock_models.py        # sinh/ cập nhật models.lock (sha256) sau khi review
    convert_bge_m3.py     # xuất ONNX + lượng tử hoá int8
    convert_prompt_guard2.py
    eval_recall_parity.py # cổng parity fp32 vs int8 (mục 5.2)
  models.lock             # ví dụ ở mục 6.2
  tests/ (unit/ adapters/ contract/ slow/ security/ bench/)
```

Quy tắc áp dụng (không lặp lại hợp đồng, chỉ nêu điểm đặc thù):
- `api/` chỉ gọi port qua `factory`; không import `onnxruntime`, `tokenizers`, `underthesea` (chỉ `adapters/` và `services/windowing.py` được phép dùng tokenizer).
- Mỗi vendor một file adapter; thêm model mới (vd. embedder khác) là thêm file + một dòng registry + đổi config, không sửa `api/`.
- Cross-cutting (đo thời gian, giới hạn đồng thời) bằng decorator cùng port (`MeteredEmbedder`, `BoundedGuard`...), không nhét vào adapter.
- Test nghiệp vụ dùng `Fake<Port>` kế thừa port, đặt ở `packages/common/testing/`.
- Leak-grep của §9.1(8) cũng áp dụng cho `packages/policy_sidecar/src/policy_sidecar/api` và `services` (trừ `windowing.py`, `models_lock.py`).

Registry (lazy import), minh hoạ:

```python
_EMBEDDERS = {
    "bge_m3_onnx": "policy_sidecar.adapters.embedder_bge_m3_onnx:BgeM3OnnxEmbedder",
}
def make_embedder(settings, lock) -> Embedder:
    return load_adapter(_EMBEDDERS, settings.embedder, "Embedder", settings=settings, lock=lock)
```

---

## 3. API

Tất cả endpoint `/v1/*` yêu cầu `Authorization: Bearer ${SIDECAR_TOKEN}`. Body JSON UTF-8, `Content-Type: application/json`. Văn bản được chuẩn hoá Unicode NFC ở **gateway** trước khi gửi; sidecar không đổi nội dung. Mọi offset là **chỉ số code point Unicode** (không phải byte, không phải UTF-16).

### 3.1 `POST /v1/embed`

Request:
```json
{
  "texts": ["Chính sách nghỉ phép năm 2026", "..."],
  "encoding": "base64",
  "normalize": true
}
```
- `texts`: 1..64 phần tử, mỗi phần tử ≤ 32 000 ký tự. `encoding`: `base64` (float32 little-endian, mặc định) hoặc `float` (mảng số, chỉ để debug). `normalize` mặc định `true` (L2).

Response 200:
```json
{
  "model": "bge-m3",
  "model_rev": "a1b2c3...",
  "dim": 1024,
  "encoding": "base64",
  "vectors": ["AAAA...", "..."],
  "truncated": [false, true],
  "tokens": [12, 8192]
}
```
- Văn bản vượt 8192 token bị cắt, `truncated[i]=true` (không lỗi). `model_rev` là revision trong `models.lock`; khách hàng (docs-mcp) nên lưu cùng vector để biết khi nào phải re-embed.
- Thứ tự `vectors` khớp `texts`.

### 3.2 `POST /v1/guard`

Request:
```json
{ "texts": ["<nội dung tool result đã mask>", "..."] }
```
- 1..16 phần tử, mỗi phần tử ≤ 200 000 ký tự.

Response 200:
```json
{
  "model": "prompt-guard-2-86m",
  "model_rev": "d4e5f6...",
  "results": [
    { "score": 0.012, "windows": 3, "truncated": false, "cached": 2 },
    { "score": 0.97,  "windows": 32, "truncated": true,  "cached": 0 }
  ]
}
```
- `score` = max qua các cửa sổ của `P(malicious)` (đã softmax), thuộc [0,1]. `windows` = số cửa sổ đã chấm, `cached` = số cửa sổ lấy từ LRU. Ngưỡng và hành động (flag/block) do gateway quyết (`01` mục 9.3).

### 3.3 `POST /v1/pii/ner`

Request:
```json
{ "texts": ["Anh Nguyễn Văn An gọi hôm qua ..."] }
```
- 1..8 phần tử, mỗi phần tử ≤ 8 000 ký tự. Văn bản dài hơn phải được gateway cắt trước (gateway cắt theo ranh giới câu).

Response 200:
```json
{
  "model": "underthesea-ner",
  "model_rev": "9.1.x",
  "results": [
    { "spans": [ { "start": 4, "end": 18, "label": "PER" } ], "truncated": false }
  ]
}
```
- Chỉ trả nhãn `PER`. Không có điểm tin cậy (CRF không cung cấp ổn định); gateway gán `score=0.7` cho span NER khi hợp nhất với regex (`01` mục 8.4).
- Nội bộ: văn bản chia khúc 4000 ký tự có chồng lấn 200, tối đa 5 khúc; phần vượt đặt `truncated=true`.
- Văn bản này **chưa** bị mask (đó là mục đích). Xem mục 8.

### 3.4 Endpoint vận hành

| Endpoint | Auth | Nội dung |
|---|---|---|
| `GET /healthz` | không | `200 {"status":"ok"}` nếu process sống |
| `GET /readyz` | không | `200` khi đã verify `models.lock` và nạp xong các model được bật; body `{"ready":true,"models":{"embed":{"model_rev":"...","dim":1024},"guard":{...},"ner":{...}}}`. Chưa sẵn sàng: `503 model_not_ready` |
| `GET /metrics` | bearer `METRICS_TOKEN` | Prometheus text |

`/readyz` không tiết lộ đường dẫn file hay cấu hình.

---

## 4. Lỗi, giới hạn, batching

Định dạng lỗi thống nhất: `{"error":{"code":"...","message":"..."}}`, không chứa nội dung request.

| HTTP | `code` | Khi nào |
|---|---|---|
| 400 | `invalid_request` | JSON sai, thiếu trường |
| 401 | `unauthorized` | thiếu/sai bearer |
| 413 | `request_too_large` | body > giới hạn (embed 1 MiB, guard 2 MiB, ner 256 KiB) hoặc vượt số phần tử/độ dài |
| 422 | `validation_error` | sai kiểu, trường lạ (`extra=forbid`) |
| 429 | `overloaded` | hàng đợi đầy hoặc quá `max_inflight`; kèm `Retry-After` (giây) |
| 503 | `model_not_ready` | chưa nạp/verify xong, hoặc endpoint bị tắt bằng `SIDECAR_*_ENABLED=false` |
| 500 | `internal_error` | lỗi khác (không kèm chi tiết) |

Batching và đồng thời:
- **Embed**: các request đồng thời được gom micro-batch (cửa sổ chờ ≤ 5 ms, tối đa 32 chuỗi/batch, sắp xếp theo độ dài để giảm padding). Một ORT session, `intra_op_num_threads` cấu hình, `inter_op=1`.
- **Guard**: gom cửa sổ 512 token của nhiều văn bản vào cùng batch (≤ 16 cửa sổ).
- **NER**: mỗi khúc là một tác vụ trong `ProcessPoolExecutor(SIDECAR_WORKERS)`; timeout mỗi khúc 2 s.
- `max_inflight` toàn service (mặc định 32); vượt thì 429 ngay (không xếp hàng vô hạn). Gateway có timeout ngắn và breaker phía client (`01` mục 1.8) nên 429 chỉ làm kích hoạt fail-policy, không treo request.
- Deadline: mỗi request có hạn `SIDECAR_REQUEST_TIMEOUT_MS` (mặc định 2000 cho guard/embed, 1500 cho NER); quá hạn trả 503/`internal_error` và huỷ công việc chưa chạy.

---

## 5. Runtime và model

### 5.1 ONNX Runtime CPU

- `onnxruntime` (CPUExecutionProvider), không dùng PyTorch/transformers trong runtime. Tokenizer: thư viện `tokenizers` (Rust) nạp `tokenizer.json` từ thư mục model đã verify.
- Graph optimization `ORT_ENABLE_ALL`, `intra_op_num_threads` = số core cấp cho sidecar (mặc định 4), `inter_op_num_threads=1`, arena bật.
- Mọi file model dạng `.onnx` hoặc `.safetensors`; không nạp pickle/`.bin`/`.pt` (mục 6).
- Một runtime duy nhất cho cả ingest và truy vấn embedding, để vector tài liệu và vector truy vấn cùng lượng tử hoá, tránh lệch không gian.

### 5.2 bge-m3 int8 và cổng parity recall@k

Xuất ONNX từ bản fp32 chính thức, lượng tử hoá int8 **động** (trọng số int8, kích hoạt tính động) bằng `onnxruntime.quantization.quantize_dynamic`. Không dùng lượng tử hoá cho phần embedding lookup nếu làm giảm chất lượng (kiểm bằng thử nghiệm).

Quy trình parity (script `eval_recall_parity.py`, chạy ở CI trước khi cập nhật `models.lock`):
1. Tập đánh giá: bộ truy vấn - tài liệu tiếng Việt nội bộ (>= 300 truy vấn có nhãn liên quan, trích từ tài liệu thật đã ẩn danh; thêm một phần tiếng Anh nếu docs có song ngữ).
2. Nhúng toàn bộ tài liệu và truy vấn bằng fp32 (tham chiếu) và int8 (ứng viên), cùng tokenizer.
3. Tính recall@k (k = 1, 5, 10) và MRR cho từng phiên bản bằng tìm kiếm cosine chính xác (brute-force, không ANN, để không lẫn lỗi chỉ mục).
4. Cổng: `recall@k(int8) >= recall@k(fp32) - 1.0 điểm phần trăm` cho mọi k đã nêu (Δ <= 1 điểm). Báo kèm khoảng tin cậy bootstrap 95%.
5. Không đạt cổng: dùng kế hoạch B theo thứ tự: (a) int8 chỉ cho encoder, giữ lớp cuối fp32; (b) fp16 hoặc fp32 trên ONNX (tốn RAM hơn, cập nhật sizing ở mục 7); (c) giữ fp32 và tăng số core. Quyết định ghi vào `models.lock` (`quantization`) và changelog.
6. Đồng thời đo: độ trễ p50/p95 theo độ dài đầu vào, throughput (văn bản/giây), RAM đỉnh. Các số này thay cho mọi ước lượng trong mục 7 khi đã đo.

Đổi bất kỳ yếu tố nào (model, revision, lượng tử hoá, tokenizer) làm `model_rev` đổi; consumer phải re-embed kho vector (docs-mcp lưu `embedding_model_rev` cùng vector).

### 5.3 Prompt Guard 2

- Model: Prompt Guard 2 (kích thước 86M), bản ONNX đã xuất; đầu ra phân lớp nhị phân benign/malicious, lấy `P(malicious)` bằng softmax.
- Cửa sổ: 512 token (kể cả token đặc biệt), bước nhảy (stride) 384 token (chồng lấn 128) để bắt chuỗi tấn công nằm ở ranh giới.
- Giới hạn: tối đa 32 cửa sổ mỗi văn bản; nếu nhiều hơn, chấm 12 cửa sổ đầu + 12 cửa sổ cuối (phần giữa bỏ qua) và đặt `truncated=true`. Lý do: kẻ tấn công thường đặt chỉ dẫn ở đầu hoặc cuối tài liệu; giới hạn chặn DoS CPU.
- `score` văn bản = max qua cửa sổ. Cache LRU 20 000 mục theo `sha256(nội dung cửa sổ đã tokenize lại thành chuỗi)`; chỉ lưu hash và điểm, không lưu văn bản.
- Ngưỡng mặc định nằm ở gateway (`gateway.yaml`: `guard.flag_threshold`, `guard.block_threshold`); sidecar không biết ngưỡng. Ngưỡng ban đầu là giả định (flag ~0.5, block ~0.9) và **phải** được hiệu chỉnh bằng pilot tiếng Việt (mục 11) trước khi bật `block`.
- Giới hạn đã biết: Prompt Guard 2 được huấn luyện chủ yếu cho tiếng Anh và một số ngôn ngữ; hiệu quả với tiếng Việt chưa được xác minh. Do đó pilot là điều kiện, không phải tuỳ chọn (R17).

### 5.4 underthesea CRF NER

- Chạy trong `ProcessPoolExecutor(max_workers=SIDECAR_WORKERS)` (mặc định 1-2), khởi tạo model một lần mỗi process (`initializer`). Lý do: CRF thuần Python/C, giữ GIL, sẽ chặn event loop nếu chạy cùng process.
- Tiền lọc (rẻ) trước khi vào pool: bỏ qua văn bản không có chữ cái viết hoa theo mẫu tên (>= 2 âm tiết viết hoa liền nhau) và văn bản rỗng; giảm tải đáng kể.
- Chia khúc 4000 ký tự (chồng lấn 200), tối đa 5 khúc/văn bản (mục 3.3); timeout 2 s mỗi khúc; khúc quá hạn bị bỏ và trả `truncated=true` (gateway vẫn có kết quả regex - `skip_on_error`).
- Chuyển nhãn: chỉ giữ thực thể `PER`; offset quy về code point trên văn bản gốc.
- Process pool bị chết/hỏng: pool được tạo lại, request hiện tại trả 503; metric `sidecar_ner_pool_restarts_total`.

---

## 6. `models.lock`: toàn vẹn chuỗi cung ứng

Mục tiêu: không bao giờ chạy một file model mà chưa được review và băm. Áp dụng cho bge-m3, Prompt Guard 2 và dữ liệu của underthesea (nếu tách file).

### 6.1 Nguyên tắc
- **Pin revision** (commit SHA đầy đủ 40 ký tự, không dùng tên nhánh/tag di động).
- **Chỉ định dạng an toàn**: `.safetensors`, `.onnx`, `tokenizer.json`, `config.json`, `special_tokens_map.json`. Cấm `.bin`, `.pt`, `.pth`, `.pkl`, `.ckpt`, file `.py`; `trust_remote_code=False` ở mọi nơi.
- **Hash đầy đủ** sha256 từng file được liệt kê; tệp thừa trong thư mục model (không có trong lock) làm sidecar từ chối khởi động.
- **Tách tải và chạy**: chỉ bước CI/build (có mạng và token HuggingFace) tải model; image runtime **không có token HF, không có mạng**, thư mục model gắn **read-only**.
- **Khoá của chính file lock**: CI tính `sha256(models.lock)` và truyền vào runtime bằng `MODELS_LOCK_SHA256`; lệch thì từ chối khởi động (chống thay lock cùng lúc thay model).

### 6.2 Ví dụ `models.lock` (TOML, theo `00-contracts.md`)

```toml
# models.lock - sinh bởi scripts/lock_models.py sau review; sửa tay là vi phạm quy trình
schema = 1

[[model]]
name        = "bge-m3"
role        = "embed"
repo        = "BAAI/bge-m3"
revision    = "0000000000000000000000000000000000000000"   # thay bằng commit SHA thật khi khoá
license     = "MIT"
quantization = "int8-dynamic"          # kết quả cổng parity mục 5.2
derived_from = "fp32 ONNX xuất bởi scripts/convert_bge_m3.py"
files = [
  { path = "bge-m3/model.int8.onnx", sha256 = "<64 hex>" },
  { path = "bge-m3/tokenizer.json",  sha256 = "<64 hex>" },
  { path = "bge-m3/config.json",     sha256 = "<64 hex>" },
]

[[model]]
name        = "prompt-guard-2-86m"
role        = "guard"
repo        = "meta-llama/Llama-Prompt-Guard-2-86M"
revision    = "0000000000000000000000000000000000000000"
license     = "Llama (kiểm tra điều khoản, mục 12)"
files = [
  { path = "prompt-guard-2/model.onnx",     sha256 = "<64 hex>" },
  { path = "prompt-guard-2/tokenizer.json", sha256 = "<64 hex>" },
  { path = "prompt-guard-2/config.json",    sha256 = "<64 hex>" },
]

[[model]]
name        = "underthesea-ner"
role        = "ner"
repo        = "pypi:underthesea"          # gói + dữ liệu model theo phiên bản cố định
revision    = "<phiên bản pin trong uv.lock>"
license     = "kiểm tra (mục 12)"
files = [
  { path = "underthesea/ner_model.bin", sha256 = "<64 hex>" },
]
```

Ghi chú: file dữ liệu của underthesea có thể là định dạng cũ (không phải safetensors/onnx). Đây là ngoại lệ **duy nhất** với quy tắc định dạng, được chấp nhận vì: model CRF nhỏ, nạp bằng thư viện chứ không `pickle.load` mã tuỳ ý do ta viết; phải ghi rõ trong review và hash cứng. Nếu thư viện nạp bằng `pickle`, coi đó là rủi ro đã biết, chỉ chấp nhận khi hash khớp và thư mục read-only. Xác minh cụ thể khi code (chưa kiểm).

### 6.3 Script tải (chạy ở CI/build, không ở runtime)

```python
# scripts/fetch_models.py - tải theo models.lock, kiểm hash, không thực thi mã từ repo model
import hashlib, os, sys, tomllib
from pathlib import Path
from huggingface_hub import snapshot_download

ALLOW = ["*.safetensors", "*.onnx", "tokenizer.json", "config.json", "special_tokens_map.json"]
DENY = ["*.bin", "*.pt", "*.pth", "*.pkl", "*.ckpt", "*.py", "*.msgpack", "*.h5"]

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main(lock_path: str, out_dir: str) -> int:
    lock = tomllib.loads(Path(lock_path).read_text(encoding="utf-8"))
    token = os.environ.get("HF_TOKEN")      # chỉ có ở CI; không bao giờ ở image runtime
    for m in lock["model"]:
        if m["repo"].startswith("pypi:"):
            continue                          # cài bằng uv.lock có hash
        local = snapshot_download(
            repo_id=m["repo"], revision=m["revision"], token=token,
            allow_patterns=ALLOW, ignore_patterns=DENY,
            local_dir=Path(out_dir) / m["name"], local_dir_use_symlinks=False,
        )
        for f in m["files"]:
            p = Path(out_dir) / f["path"]
            if not p.exists() or sha256(p) != f["sha256"]:
                print(f"HASH MISMATCH: {f['path']}", file=sys.stderr)
                return 1
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
```
Ghi chú: `snapshot_download` không có tham số `trust_remote_code`; chính sách `trust_remote_code=False` được áp dụng bằng cách không bao giờ dùng `transformers.AutoModel` trong sidecar (runtime không có `transformers`) và lọc `*.py`. Bản ONNX int8 của bge-m3 do ta tự xuất (`convert_bge_m3.py`) rồi đưa vào artifact nội bộ; lock ghi hash artifact đó. Script `lock_models.py` sinh `models.lock` mới sau review bằng người.

### 6.4 Kiểm tra lúc khởi động (`services/models_lock.py`)

1. Đọc `MODELS_LOCK_PATH` (mặc định `/app/models.lock`); tính sha256, so với `MODELS_LOCK_SHA256` nếu đặt (prod bắt buộc đặt).
2. Với mỗi model bật (`SIDECAR_*_ENABLED`): kiểm file tồn tại, sha256 **toàn bộ** nội dung khớp, kích thước hợp lý; thư mục không chứa file ngoài danh sách; đuôi file thuộc allowlist.
3. Một sai lệch bất kỳ: log `models_lock_mismatch` (tên file, không nội dung), thoát process mã khác 0; `/readyz` không bao giờ `200`.
4. Chỉ sau khi đạt mới tạo `InferenceSession` và đặt `ready=true`. Thời gian hash (vài trăm MB) được tính vào thời gian khởi động (đo; ước tính vài giây).
5. Metric `sidecar_model_info{name,model_rev}=1` và `sidecar_models_lock_verified=1`.

CI thêm kiểm tra: lock hợp lệ theo schema; không có revision là nhánh; không có đuôi file cấm; hash trong lock bằng hash artifact build; quét `.pth`/`sitecustomize.py` lạ như gateway.

---

## 7. Cấu hình, tài nguyên, sizing

### 7.1 Biến môi trường (`SIDECAR_*`, khớp `00-contracts.md` §7)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `SIDECAR_PORT` | `8010` | cổng lắng nghe |
| `SIDECAR_TOKEN` | (bắt buộc) | bearer gateway/service gọi vào; từ secret |
| `METRICS_TOKEN` | (bắt buộc ở prod) | bearer cho `/metrics` |
| `MODELS_LOCK_PATH` | `/app/models.lock` | đường dẫn lock |
| `MODELS_LOCK_SHA256` | (prod bắt buộc) | hash của file lock |
| `SIDECAR_MODELS_DIR` | `/models` | thư mục model (read-only) |
| `SIDECAR_EMBED_ENABLED` | `true` | bật `/v1/embed` |
| `SIDECAR_GUARD_ENABLED` | `true` | bật `/v1/guard` |
| `SIDECAR_NER_ENABLED` | `true` | bật `/v1/pii/ner` |
| `SIDECAR_WORKERS` | `2` | số process NER; ORT dùng thread trong process chính |

Các tham số tinh (ngưỡng batch, cache LRU, giới hạn cửa sổ) nằm ở `config/sidecar.yaml` (đọc lúc khởi động, từ git), không đặt qua API.

### 7.2 Sizing (ước tính, phải đo lại ở E1/E4)

| Thành phần | Ước tính RAM | Ghi chú |
|---|---|---|
| bge-m3 int8 ONNX | 0.6-0.8 GB | file ~0.6 GB + arena |
| Prompt Guard 2 (86M) ONNX | ~0.2-0.3 GB | |
| underthesea + process pool | 0.3-0.5 GB / process | tuỳ phiên bản, model CRF |
| Python + FastAPI | ~0.1 GB | |
| **Tổng** | **~1.5-2.2 GB**, cấp 3 GB giới hạn | |

CPU: 4 vCPU là điểm xuất phát. Tất cả số trên là ước lượng thiết kế, **chưa đo**. Cách kiểm chứng: chạy `bench/` với tải mô phỏng (mục 10) và ghi vào bảng kết quả E1 trước khi dùng làm cam kết.

Triển khai: 1 container `policy-sidecar` (compose), `read_only: true`, `cap_drop: [ALL]`, `user` non-root, `tmpfs` cho `/tmp`, thư mục model mount `:ro`, mạng `core` (không có `egress`), không có secret nào ngoài `SIDECAR_TOKEN`, `METRICS_TOKEN`. Scale ngang bằng cách thêm bản sao sau một DNS nội bộ; sidecar không có trạng thái nên cân bằng round-robin đủ dùng.

---

## 8. Xác thực, mạng, bảo mật

- Bearer `SIDECAR_TOKEN`: so sánh bằng `hmac.compare_digest`; thiếu/sai -> 401 (cùng thông điệp, không phân biệt). Token xoay vòng qua secret store; hỗ trợ hai giá trị cùng lúc (`SIDECAR_TOKEN`, `SIDECAR_TOKEN_PREV`) để xoay không gián đoạn. `/healthz`, `/readyz` không cần token (không chứa dữ liệu nhạy cảm); `/metrics` dùng `METRICS_TOKEN`.
- Mạng: chỉ trong mạng Docker `core`; không publish cổng ra host ở prod; không có route ra ngoài. mTLS giữa gateway và sidecar để M7.
- Dữ liệu: **`/v1/pii/ner` nhận văn bản chưa mask**, nên sidecar là thành phần xử lý PII thô. Hệ quả: không log nội dung (kể cả khi lỗi, kể cả `DEBUG`), không ghi đĩa, không có core dump (`ulimit -c 0`), `tmpfs` cho `/tmp`, không có biến môi trường chứa nội dung. Guard và embed nhận văn bản **đã** mask (gateway chạy regex trước, `01` mục 2.6).
- Đầu vào: Pydantic `extra=forbid`, giới hạn kích thước ở tầng ASGI (từ chối trước khi parse), giới hạn số phần tử, độ dài, cửa sổ; không có tham số đường dẫn hay URL.
- Không có endpoint cập nhật model/config/ghi file. Nạp model chỉ lúc khởi động (mục 6).
- Supply chain: `uv.lock` có hash, image pin digest, quét `.pth`; ngoài ra `models.lock` (mục 6).
- Log: JSON, có `request_id` (nhận từ header `x-request-id` của gateway), endpoint, kích thước, thời lượng, mã lỗi; **không** có nội dung văn bản.

---

## 9. Metrics, log, SLO

Metric Prometheus (prefix `sidecar_`, label cố định, không label theo nội dung/ID người dùng):

| Metric | Loại | Label |
|---|---|---|
| `sidecar_requests_total` | counter | `endpoint`, `code` |
| `sidecar_request_duration_seconds` | histogram | `endpoint` |
| `sidecar_batch_size` | histogram | `endpoint` |
| `sidecar_queue_wait_seconds` | histogram | `endpoint` |
| `sidecar_inflight` | gauge | |
| `sidecar_rejected_total` | counter | `reason` (`overloaded`, `too_large`, `not_ready`) |
| `sidecar_guard_cache_hits_total` / `_misses_total` | counter | |
| `sidecar_guard_windows` | histogram | |
| `sidecar_embed_tokens_total` | counter | |
| `sidecar_ner_pool_restarts_total` | counter | |
| `sidecar_model_info` | gauge | `name`, `model_rev` |
| `sidecar_models_lock_verified` | gauge | |

SLO (chỉ tiêu nghiệm thu, đo ở E1/E4; số chưa đo):
- p95 `/v1/guard` cho văn bản ~1k token <= 150 ms; p95 `/v1/embed` 1 chuỗi ngắn <= 60 ms; p95 `/v1/pii/ner` 1 khúc <= 80 ms; tất cả ở tải <= 20 RPS/endpoint trên 4 vCPU.
- Tỉ lệ 429/503 < 0.5% ở tải thiết kế.

Alert gợi ý: `/readyz` 503 > 1 phút; `sidecar_rejected_total{reason="overloaded"}` tăng; p95 vượt SLO 10 phút. Phía gateway có thêm `gateway_sidecar_*` (`01` mục 15).

---

## 10. Kế hoạch test

Cấu trúc `packages/policy_sidecar/tests/`: `unit/`, `adapters/`, `contract/`, `slow/`, `security/`, `bench/`.

- **Unit** (không model thật): `windowing` (cửa sổ, stride, giới hạn 12+12, `truncated`); `guard_cache` (LRU, chỉ lưu hash); `batching`; `models_lock` (khớp/lệch hash, tệp thừa, đuôi cấm, lock bị sửa -> `MODELS_LOCK_SHA256` lệch); chia khúc NER và quy đổi offset code point (có dấu, tổ hợp NFC/NFD, emoji); schema `extra=forbid`.
- **Adapters**: `Fake*` kế thừa port để test API; mỗi factory có test "tên đúng chạy, tên lạ báo lỗi kèm danh sách" (§9.1(9)).
- **Contract**: test API (ASGI client) với fake adapter - mọi mã lỗi ở mục 4, 401/413/422/429/503, định dạng response, thứ tự kết quả; bài kiểm "response không bao giờ chứa nội dung request".
- **Slow** (`pytest -m slow`, có model thật, CI đêm): embed trả `dim=1024`, vector L2 = 1; độ tương đồng cặp câu tiếng Việt đồng nghĩa > cặp không liên quan; guard bắt mẫu injection tiếng Anh đơn giản và không bắt câu bình thường; NER bắt tên người tiếng Việt mẫu; bộ nhớ không rò (RSS ổn định sau 10 phút tải).
- **Parity**: `eval_recall_parity.py` (mục 5.2) là cổng bắt buộc khi đổi model/lượng tử hoá.
- **Security**: lock sai hash -> process thoát, không `ready`; thêm file lạ vào thư mục model -> từ chối; `.pkl` giả -> từ chối; fuzz body (JSON lồng sâu, chuỗi cực dài, Unicode lạ, null byte) không làm crash; ReDoS/DoS: văn bản 200k ký tự, 1000 cửa sổ -> bị giới hạn đúng, thời gian có trần; token sai không lộ thông tin thời gian (kiểm thô).
- **Tải** (`bench/`): Locust/k6 đa endpoint; đo p50/p95/p99, RPS tối đa trước khi 429, RAM đỉnh; chạy lại trên phần cứng đích để thay số ước tính ở mục 7.
- **Tích hợp với gateway** (job chậm ở `01` mục 18.2): kill sidecar -> fail-policy; chậm sidecar -> timeout đúng; token sai -> gateway ghi `gateway_sidecar_errors_total`.
- Leak-grep: §9.1(8) và grep thứ hai cho `packages/gateway/src` (không có `onnxruntime|torch|tokenizers|transformers|sentence_transformers|huggingface_hub`); kiểm `packages/policy_sidecar/src/policy_sidecar/api` không import vendor.

---

## 11. Pilot guard tiếng Việt (R17)

Vấn đề: Prompt Guard 2 chưa được chứng minh trên tiếng Việt (có dấu, không dấu, trộn Anh-Việt). Không bật `block` khi chưa qua pilot.

Dữ liệu:
- **Positive** (tấn công): (a) mẫu AgentDojo và garak được dịch sang tiếng Việt rồi người review; (b) >= 200 câu tiếng Việt viết tay gồm: chỉ dẫn ghi đè hệ thống, yêu cầu lộ system prompt, "bỏ qua các hướng dẫn trước", ra lệnh gọi tool ghi, đánh cắp dữ liệu qua đường dẫn/URL, mã hoá (base64, leetspeak), tiếng Việt không dấu, trộn Anh-Việt, nhúng trong email/ticket/tài liệu dài. Mỗi mẫu gắn nhãn loại tấn công và vị trí (đầu/giữa/cuối).
- **Negative** (lành tính): 500-1000 tài liệu/ticket/email nội bộ tiếng Việt đã ẩn danh (hướng dẫn, quy trình, chính sách, log lỗi, câu lệnh có mệnh lệnh hợp lệ như "hãy làm theo các bước sau"). Phải gồm cả nội dung có ngôn ngữ mệnh lệnh để đo dương tính giả thực tế.

Phương pháp:
1. Chấm điểm bằng đúng sidecar (cửa sổ, stride, max-pooling như thực tế).
2. Báo **recall tại FPR 1% và 0.1%** (chọn ngưỡng từ negative), kèm khoảng tin cậy Wilson 95%; tách theo ngôn ngữ (Việt có dấu, không dấu, trộn, Anh), theo loại tấn công và vị trí cửa sổ.
3. Báo đường cong ROC/PR và phân bố điểm negative theo loại tài liệu.

Tiêu chí go/no-go (đề xuất, **chủ dự án chốt trước khi chạy**): FPR <= 1% ở ngưỡng chọn, recall tiếng Việt >= 70% tại FPR đó, recall tiếng Anh >= 90%. Nếu không chốt trước, kết quả không được dùng để bật `block`.

Kết quả:
- Đạt: bật `flag` (mặc định) và có thể `block` cho tool result từ nguồn bên ngoài; ghi ngưỡng vào `gateway.yaml` kèm phiên bản dữ liệu pilot và `model_rev`.
- Không đạt: kế hoạch B theo thứ tự chi phí: (1) bổ sung luật regex/heuristic tiếng Việt cho mẫu phổ biến (đặt trong gateway như một `InjectionGuard` adapter, không phải ngoại lệ ngoài port); (2) bộ phân loại nhỏ trên vector bge-m3 huấn luyện từ dữ liệu pilot; (3) tinh chỉnh Prompt Guard 2 bằng dữ liệu tiếng Việt (cần dữ liệu và đánh giá kỹ về giấy phép). Trong lúc đó guard chỉ `flag` + spotlighting; chặn thao tác ghi vẫn dựa vào token phê duyệt ở MCP (không phụ thuộc guard).
- Giới hạn thời gian: pilot được time-box (ví dụ 2 tuần công việc), kết quả ghi vào `docs/reviews/` hoặc phụ lục tài liệu eval (`04`); lặp lại khi đổi model/revision.

---

## 12. Giấy phép

| Thành phần | Giấy phép | Trạng thái xác minh |
|---|---|---|
| Prompt Guard 2 (Meta Llama Prompt Guard 2) | Llama Community License; repo gated, cần chấp nhận điều khoản | **Chưa xác minh** điều khoản áp dụng cho dùng nội bộ doanh nghiệp; cần pháp chế duyệt trước khi lên prod |
| bge-m3 (BAAI) | MIT | Cần xác nhận lại trên trang model tại revision đã pin |
| underthesea | Kiểm tra giấy phép của phiên bản cụ thể (có thể là GPL-3.0 ở một số phiên bản) | **Chưa xác minh**; nếu copyleft ảnh hưởng, vì sidecar là service riêng nên ảnh hưởng chủ yếu ở việc phân phối image; phương án thay thế: NER khác sau cùng port `PiiDetector` |
| onnxruntime, tokenizers, huggingface_hub | MIT/Apache-2.0 (theo công bố của dự án) | Ghi trong báo cáo SBOM |

Mỗi `[[model]]` trong `models.lock` ghi trường `license`; CI chặn khi trường này rỗng. Quy trình thêm model mới: review giấy phép, hash, định dạng file, kết quả parity/pilot, rồi mới cập nhật lock.

---

## 13. Phụ thuộc contracts

Khớp `00-contracts.md` v1.2 (§7 env, §9.2 adapter, models.lock). Đã chốt bởi D14: `MODELS_LOCK_SHA256`, `SIDECAR_TOKEN_PREV`, `acme-embed` → `sidecar/embed`. Điểm cần thống nhất thêm:
- Port `PiiDetector` được sidecar dùng ở phía server với adapter `underthesea_ner`; contracts hiện liệt kê cho gateway.
- `config/sidecar.yaml` (ngưỡng batch, cache LRU, giới hạn cửa sổ) (biến `MODELS_LOCK_SHA256`, `SIDECAR_TOKEN_PREV` đã chốt bởi D14).
- Trường `model_rev` trong response embed cần được docs-mcp lưu cùng vector (`02`/`04`).
- Giới hạn kích thước và mã lỗi ở mục 4 là hợp đồng giữa gateway và sidecar; đổi thì cập nhật đồng thời `01` mục 1.8.
