# Review vòng 2 — Bộ thiết kế v1.2 (Opus)

Ngày: 2026-10-29. Phạm vi: `docs/design/00..06`, `DECISIONS-v1.2.md` (D0–D14), `ROADMAP.md`, `SOLUTION.md`, `adr/ADR-001`, đối chiếu với `reviews/review-01-opus.md` (R01–R27).
Vai trò: kiến trúc sư phần mềm + chuyên gia bảo mật. Bối cảnh: sản phẩm nội bộ tự phát triển, self-host, đội nhỏ.
Quy ước dẫn chứng: `00:126` = `design/00-contracts.md` dòng 126; `05 §4.2` = mục 4.2 của `design/05-approval-flow.md`. Chỉ báo mâu thuẫn khi đã thấy cả hai chỗ. Những điểm phụ thuộc hành vi phần mềm bên ngoài (Keycloak) được ghi rõ là "cần xác minh".

---

## 1. Bảng truy vết R01..R27

| Mã | Chủ đề (review-01) | Trạng thái | Dẫn chứng / nhận xét |
|---|---|---|---|
| R01 | Approval không WYSIWYS | Đã giải quyết (còn hở ở render, xem N03/N04) | D1; 05 §3–§5: intent do tickets-mcp tính và ký, `commit_intent` không nhận args, `expected_updated_at` nằm trong intent. Lỗ còn lại: không có quy tắc buộc mọi trường được ký phải được hiển thị. |
| R02 | Phạm vi quá rộng | Đã giải quyết (qua chia milestone) | D0; ROADMAP M0–M7 tách theo giá trị, mỗi milestone có DoD riêng. |
| R03 | E4 tautology | Giải quyết một phần | D10, 04 §13 tách E4a/E4b/E4c, có approver oracle + naive (04:1851, 1867). Nhưng DoD M5 và SOLUTION (mục E4) vẫn còn câu "ASR thao tác ghi = 0%", trái với E4a(iii) báo cáo trung thực tỉ lệ bị duyệt bởi approver ngây thơ (xem N20). |
| R04 | Đóng góp học thuật mờ | Bị bác / không còn áp dụng — hợp lý | D0: dự án là sản phẩm, không phải đồ án; đóng góp đo bằng giá trị vận hành. |
| R05 | Khoá ký nằm trong Chainlit | Đã giải quyết | D1/D13: tách `approval-signer` (8310), khoá không còn trong UI. Hở cấu hình D13 xem N01/N02. |
| R06 | Gateway ôm quá nhiều | Đã giải quyết | D2, 06: tách `policy-sidecar` (8010); gateway bị cấm nạp onnx/torch. Phát sinh rủi ro mới N15/N16. |
| R07 | Chuỗi cung ứng model | Đã giải quyết | D3: `models.lock` + `MODELS_LOCK_SHA256`, kiểm khi khởi động (06). |
| R08 | Cache poisoning / side-channel | Đã giải quyết | D4: khoá cache theo tenant/sub + classification, không cache khi có tool result. |
| R09 | Cache không áp dụng cho agent | Đã giải quyết | D4: phạm vi cache ghi rõ, E3 tách trace agent (04:1841). |
| R10 | Router thiếu baseline | Giải quyết một phần | Đã có baseline router ngẫu nhiên/heuristic (D10). DoD M4 "≥50% tại iso-quality" gần như tự đạt do chênh giá 20× (N19). |
| R11 | Dữ liệu/judge | Đã giải quyết (trên giấy) | 04 §12: κ, judge khác họ, kiểm mẫu 10%, `e3-trace`. |
| R12 | PII trong checkpoint | Đã giải quyết | D7: checkpoint mã hoá, AAD=thread_id, retention 30 ngày; spike D. Tương tác với taint xem N12. |
| R13 | E7 không đo được | Đã giải quyết (trên giấy) | D10 định nghĩa lại E7. |
| R14 | Embedding parity | Giải quyết một phần | D14: một runtime embed trong sidecar. Nhưng sidecar chỉ có ở M4, M1–M3 không có runtime embedding thật (N17). |
| R15 | Audit có thể giả | Đã giải quyết (lưu ý khoá) | D6: HMAC hash chain + anchor, audit cùng transaction. Khoá HMAC dùng chung nhiều service (N14). |
| R16 | Confused deputy / rò rỉ chéo | Giải quyết một phần | D8 taint + docs-mcp fail-closed (02:803). Còn bypass theo TTL và chiều phòng ban (N12). |
| R17 | Guard kém với tiếng Việt | Đã giải quyết | Pilot 13.4, D2 "guard=score-only" nếu chưa qua pilot (04:1863). |
| R18 | Quá nhiều port | Phần lớn đã giải quyết | D11 gộp và quy định port tối thiểu; vẫn khoảng 27 port, D14 còn thêm AnchorStore/IntentIssuer. Chấp nhận được nếu fake đi kèm. |
| R19 | Raw SQL analytics | Đã giải quyết | D9: chỉ truy vấn tham số hoá từ catalogue. |
| R20 | Chế độ degraded | Đã giải quyết | D5: ma trận degraded theo thành phần. Mặc định guard fail_open là lựa chọn có rủi ro (N15). |
| R21 | Thiếu spike | Đã giải quyết | M0 có 4 spike A–D + pilot, mỗi cái có phương án B. |
| R22 | E1 | Đã giải quyết | D10. |
| R23 | E8 | Đã giải quyết | D10. |
| R24 | Presidio | Đã giải quyết | D12. |
| R25 | Nguồn CVE đơn lẻ | Đã giải quyết (sót) | D12 yêu cầu mã định danh có nguồn; SOLUTION:36 vẫn nêu CVE-2026-42208 kèm ghi chú "cần ghi mã định danh", 00:146 vẫn nhắc CVE-2026-89032 (N21). |
| R26 | Regex PERSON | Đã giải quyết | D12: NER underthesea thay regex. |
| R27 | Advisory lock | Giữ nguyên — hợp lý | D12: lý do vận hành rõ, có UNIQUE làm lưới an toàn. |

Tổng: 20 đã giải quyết, 5 một phần (R03, R10, R14, R16, R18 phần lớn), 1 bị bác hợp lý (R04), 1 giữ nguyên hợp lý (R27). Đề xuất gộp 2 Redis (review-01) bị bác ở D12 — hợp lý vì tách ACL/độ bền.

---

## 2. Vấn đề mới

Tổng hợp: **0 Critical, 7 High, 11 Medium, 8 Low**.

### 2.1 Luồng intent / approval / D13

#### N01 — High — Cấu hình Keycloak hiện tại không thực hiện được D13
- **Mô tả.** D13 yêu cầu: token đăng nhập của chat-ui chỉ có `aud=agent-service`; khi duyệt, backend Chainlit exchange (RFC 8693, standard token exchange V2) lấy token `aud=approval-signer`. Realm JSON ở 04 §4.2 (khoảng dòng 1046–1055) không phản ánh điều đó: client `chat-ui` không bật `standard.token.exchange.enabled`; không có client scope/audience mapper nào cho `approval-signer`; client `approval-signer` không có trong JSON; `aud-agent-service` được mô tả là "scope mặc định của chat-ui" nhưng `defaultClientScopes` của chat-ui chỉ có `acme-claims`.
- **Mâu thuẫn trực tiếp.** Test ở 04:1068 "exchange bởi client khác agent-service phải 403" trái với D13, nơi chat-ui là client phải exchange thành công.
- **Cần xác minh (spike C).** Theo tài liệu Keycloak standard token exchange V2, client gọi exchange phải nằm trong `aud` của subject token. Token đăng nhập chỉ có `aud=agent-service` thì chat-ui có thể bị từ chối.
- **Kịch bản hỏng.** Khi code M1, đội gặp lỗi exchange và "sửa nhanh" bằng cách gắn scope `approval-signer` làm default của chat-ui. Token đăng nhập (mà agent cầm) khi đó có `aud=approval-signer`, agent bị chiếm tự gọi signer được. D13 bị vô hiệu mà không test nào báo (xem N02).
- **Sửa.** Viết lại realm JSON đúng D13: client `approval-signer` (bearer-only); scope `aud-approval-signer` là **optional** scope của chat-ui; bật TE V2 cho chat-ui; nếu luật "requester ∈ aud" đúng thì thêm `chat-ui` vào aud token đăng nhập bằng mapper riêng và ghi rõ hệ quả. Sửa 04:1068. Thêm assert vào spike C: token đăng nhập **không** có `approval-signer` trong `aud`.

#### N02 — High — Test D13 dùng sai token nên không bắt được lỗi cấu hình
- **Mô tả.** F22 (05:425), DoD M1 (ROADMAP:79), DoD M5 (ROADMAP:140) và E4c (04:1917) đều thử token `azp=agent-service`. Nhưng thứ agent thật sự cầm là token đăng nhập được chuyển tiếp (`azp=chat-ui`, `aud=agent-service`; 03 §1.3, 00:537). Kiểm `azp` không chặn token này; lớp chặn thật là `aud`.
- **Kịch bản hỏng.** Cấu hình sai như N01, F22 vẫn xanh vì token thử có `azp=agent-service`. Token đăng nhập có `aud=approval-signer`, agent gọi `/v1/approvals` thành công.
- **Sửa.** Thêm ca F22b: lấy đúng token đăng nhập mà agent nhận và gọi signer → phải 401/403. Thêm kiểm tra tĩnh khi khởi động signer: từ chối token có `azp=chat-ui` nếu không có claim chứng minh đã qua exchange (vd `act`/thời điểm cấp từ exchange), hoặc chỉ chấp nhận token có `aud` **duy nhất** là `approval-signer`.

#### N03 — High — WYSIWYS bị hở ở bước render: trường được ký nhưng không được hiển thị
- **Mô tả.** Signer dựng `display` theo "mẫu cố định theo op (op→title/diff fields)" (05:308). UI chỉ vẽ `display.diff` (03 §9.4). Trong khi đó `commit_intent` thực thi `args_canonical`. Không có quy tắc nào buộc mọi khoá của `args_canonical` (vd `internal`, `assignee_dept`, `priority`, `classification`) xuất hiện trong `display`.
- **Kịch bản hỏng.** Thêm trường `internal` vào `prepare_add_comment` ở một bản phát hành sau nhưng quên cập nhật mẫu render. Agent bị injection đặt `internal=false` cho ghi chú chứa dữ liệu nội bộ. Người duyệt thấy đúng nội dung bình luận và duyệt; comment hiện cho khách hàng.
- **Sửa.** Quy tắc cứng: signer từ chối ký nếu `keys(args_canonical) ⊄ keys(display.after) ∪ keys(target)`; mẫu render là "liệt kê mọi khoá, đánh dấu khoá nhạy cảm", không phải danh sách chọn lọc. Thêm property test sinh args ngẫu nhiên cho từng op.

#### N04 — Medium — Giả mạo hiển thị bằng Unicode (bidi, ký tự điều khiển, confusable)
- **Mô tả.** Văn bản do agent dựng đi vào `after`. UI chỉ `esc()` cho bảng markdown (03:1009); NFC không chặn RLO/LRI, zero-width, homoglyph.
- **Kịch bản hỏng.** Tiêu đề chứa U+202E đảo chiều, người duyệt đọc "Đóng ticket #1024" trong khi target thật là #4201; hoặc tên người nhận dùng chữ Cyrillic giống Latin.
- **Sửa.** Signer từ chối (hoặc hiển thị mã) các ký tự Cc/Cf/bidi; render target bằng ID số + tên lấy từ DB, không lấy từ văn bản agent; gắn `risk_flags:["mixed_script"]` khi trộn hệ chữ.

#### N05 — High — Hợp đồng Redis intent tự mâu thuẫn: có lưu JWS hay không
- **Hai phía.** 00:133 "Không bao giờ lưu ... intent JWS đầy đủ (chỉ lưu hash, sub, status)" và 00:126 HASH chỉ có `{sha256, sub, status}`. Ngược lại 05:104 (sơ đồ có HSET jws), 05 §4.2 dòng 219, 05 §6 dòng 357 lưu `jws`; 02 §6.7 dòng 1175/1184 hàm `load` verify JWS đọc từ Redis.
- **Hệ quả.** `commit_intent` không nhận JWS. Nếu làm theo 00 thì tickets-mcp không có nguồn `args_canonical` lúc commit. Nếu làm theo 05/02 thì 00 sai và quy tắc tối thiểu hoá dữ liệu trong Redis bị phá (nội dung ticket nằm trong Redis 330s).
- **Sửa.** Chọn một: lưu JWS (khuyến nghị — cần để commit) và sửa 00:126/133, đồng thời nêu rõ dữ liệu này thuộc phân loại của ticket và ACL `redis-state` phải chặn mọi client khác tickets-mcp.

#### N06 — High — Tên trạng thái và thứ tự chuyển trạng thái intent không nhất quán; có race
- **Hai phía.** 00:126 dùng `pending|committed|cancelled` và "commit: kiểm ... rồi đặt committed (Lua, atomic)" — tức đặt committed trước khi ghi DB. 05 §3.3/§3.4 và 02:1198, 1222 dùng `aborted`, đặt committed **sau** khi DB commit (02:1199).
- **Kịch bản hỏng.** Luồng `approval_expired`/`needs_new_approval` có thể sinh hai approval khác `jti` cho cùng intent. Hai `commit_intent` song song đều qua kiểm `status=pending`. Lần 1 ghi DB thành công; lần 2 gặp `conflict` hoặc UNIQUE violation và đặt `pending→aborted` trước khi lần 1 kịp đặt `committed`. Kết quả: DB đã ghi nhưng intent ghi "aborted", audit và UI báo thất bại; người dùng thử lại, sinh thao tác trùng với op không có UNIQUE tự nhiên.
- **Sửa.** Một máy trạng thái duy nhất trong 00: `pending → committing (Lua CAS, gắn jti) → committed | failed`; chỉ owner `jti` được chuyển tiếp; UNIQUE(intent_id) violation ánh xạ thành `approval_replayed` (không phải `conflict`). Thống nhất `cancelled`/`aborted`.

#### N07 — Low — UNIQUE(intent_id) chỉ có ở 02, thiếu trong schema chuẩn
- 02:1143 dựa vào `UNIQUE(intent_id)` làm lưới chống replay độc lập Redis; schema ở 00 §3.3 (dòng 308) không có ràng buộc này. Migration sinh từ 00 sẽ thiếu. **Sửa:** đưa vào 00 §3.3.

#### N08 — Medium — Giá trị mặc định `tickets.classification` mâu thuẫn
- 00:299 `DEFAULT 1`, và 00:658 (D14) bác phương án "DEFAULT 0 + INTERNAL_FLOOR". Nhưng 05 §7.2 dòng 374 ghi "mặc định 0", 05 §14#2 vẫn liệt kê env `INTERNAL_FLOOR`, 02:872 còn `INTERNAL_FLOOR=1`.
- **Kịch bản hỏng.** Người viết tickets-mcp theo 05 đặt mặc định 0 → ticket mới thấy được bởi clearance thấp nhất; taint so với floor 0 luôn sinh `possible_downgrade` giả, gây mệt mỏi cảnh báo.
- **Sửa.** Sửa 05 §7.2, 05 §14#2, 02:872 theo 00.

#### N09 — Medium — Mã lỗi khi `sub` không khớp tại signer
- 00 §4 bảng (dòng 347) và 00 §4.1 (dòng 391): 403 `forbidden`. 05 §5.3 dòng 308 và ca F08: 422 `intent_mismatch` (reason=sub). Test fault-injection sẽ đỏ ở một trong hai cách cài.
- **Sửa.** Chọn 403 `forbidden` (không tiết lộ intent tồn tại), sửa 05 và F08.

#### N10 — Medium — Không ràng buộc `kid` ↔ `iss` khi verify intent; tên adapter lệch
- 05 §5.2 đặt public key intent ở `<kid>.pub` (phẳng), 05 §5.5 dùng `<iss>/<kid>.pub`. 00:633 gọi adapter `es256_jwt`, 05 §5.2 gọi `es256_file.py`.
- **Kịch bản hỏng.** Thêm MCP thứ hai có khả năng ký intent (hr-mcp, 03 §16). Với bố cục phẳng, signer tìm khoá theo `kid` bất kể `iss`; hr-mcp bị chiếm ký intent `iss=tickets-mcp, op=close_ticket`, signer chấp nhận và render như tickets — confused deputy giữa các MCP.
- **Sửa.** Bố cục `<iss>/<kid>.pub` là chuẩn; verify phải tra khoá theo cặp `(iss, kid)` và kiểm `op` thuộc danh mục của `iss`. Thống nhất tên adapter.

#### N11 — Low — Xoay khoá: JWKS hay file; 10 hay 15 phút
- D14/00:405 nói "JWKS công bố"; 05 §5.5 nói dùng file, "không fetch từ mạng". 04:1110 ghi overlap 10 phút; 04:2368 và 05 ghi ≥15 phút. **Sửa:** ghi "file mount, overlap ≥15 phút (≥ TTL intent 330s + approval 120s + biên)" ở một chỗ.

#### N12 — High — Taint bị vượt theo thời gian và theo chiều phòng ban
- **Mô tả.** (a) Taint TTL 1800s (00:128) trong khi checkpoint/summary giữ nội dung 30 ngày (D7) → quay lại thread sau 30 phút hoặc hôm sau, nội dung mật vẫn nằm trong ngữ cảnh nhưng không còn cờ. (b) Taint chỉ so clearance, bỏ qua phòng ban: tài liệu HR class 1 → ticket giao cho IT (class 1 mặc định) → không sinh cờ, nhưng IT đọc được. (c) `audience_floor` lấy từ `tickets.classification`, còn RLS `tk_select` (02:1081) quyết định người đọc theo dept/role — nhãn không phản ánh người đọc thật. (d) analytics/ticket không sinh taint (05 §7.5 đã ghi nhận).
- **Kịch bản hỏng.** Hôm qua user HR hỏi về bảng lương (class 1, dept HR). Hôm nay mở lại thread, nhờ "tạo ticket cho IT tóm tắt cuộc trao đổi hôm qua". Taint đã hết hạn, thẻ duyệt không có `possible_downgrade`, nội dung lương vào ticket IT.
- **Sửa.** Taint gắn vào `thread_id` và sống bằng vòng đời checkpoint (xoá cùng checkpoint), không theo TTL cố định; taint mang `(classification, dept_set)`; `audience_floor` tính từ chính sách RLS (tập dept/role đọc được ticket đích) thay vì một số nguyên.

#### N13 — Medium — Từ chối không huỷ intent; mệt mỏi phê duyệt
- Không có tool huỷ intent (03:840); signer stateless. Intent bị từ chối vẫn `pending` tới 300s; agent bị chiếm có thể trình lại cùng intent. UI giới hạn 3 lần/intent (03 §7.4) nhưng agent chỉ cần `prepare` lại để có intent mới.
- **Sửa.** Nút "Từ chối" gọi endpoint huỷ (qua backend UI, token user) đặt `cancelled`; giới hạn số thẻ/thread/giờ ở UI backend, không dựa vào agent.

### 2.2 Audit, sidecar và bề mặt tấn công

#### N14 — Medium — `AUDIT_HMAC_KEY` dùng chung cho nhiều service
- 00 §7 (dòng 491, 496, 497): gateway, docs-mcp, tickets-mcp cùng khoá; anchor `sig` dùng cùng khoá. Chiếm một MCP là giả được chuỗi audit của gateway và anchor.
- **Sửa.** Mỗi service một khoá (dẫn xuất HKDF từ khoá gốc theo tên service, khoá gốc không nằm trong service); anchor ký bằng khoá riêng của job anchor.

#### N15 — High — Guard và NER bị bỏ qua khi sidecar quá tải
- 01:356 guard mặc định `fail_policy: fail_open`; 01:357/1341 NER `skip_on_error`; sidecar `max_inflight 32` trả 429. Chỉ fail-closed khi `GW_PII_STRICT=1` + block.
- **Kịch bản hỏng.** Kẻ tấn công cài tài liệu lớn vào kho; nhiều phiên truy xuất cùng lúc làm sidecar 429. Gateway bỏ guard, payload injection đi thẳng vào model; cùng lúc NER bị bỏ, tên người lộ ra provider ngoài. Quá tải có thể do chính kẻ tấn công gây ra.
- **Sửa.** Với nội dung tool/RAG: guard **fail_closed** (hoặc thay nội dung bằng cảnh báo "không kiểm được"); NER fail-closed cho request ra provider ngoài, fail-open chỉ cho model self-host; hàng đợi ưu tiên theo nguồn; metric + alert khi tỉ lệ skip > 0.

#### N16 — Medium — Sidecar là bề mặt tấn công mới với vùng ảnh hưởng rộng
- Sidecar xử lý văn bản thô bằng thư viện native; underthesea có thể nạp pickle (06 §6.2); mạng `core` phẳng nên sidecar với tới Keycloak, Redis, agent, signer; một `SIDECAR_TOKEN` dùng chung cho mọi client; sidecar bị chiếm có thể đầu độc embedding lúc ingest (vector sai → truy xuất có chủ đích). underthesea là GPL (rủi ro thấp với self-host không phân phối).
- **Sửa.** Mạng riêng `sidecar-net` chỉ gateway + ingest với tới; sidecar không có egress; chạy read-only rootfs, non-root, seccomp; khoá hash file pickle trong `models.lock`; token riêng theo client.

### 2.3 Roadmap, vận hành và tài liệu

#### N17 — Medium — Không có runtime embedding thật ở M1–M3
- D14 chuyển `acme-embed` → `sidecar/embed`; sidecar chỉ có ở M4 (ROADMAP M4 "chuyển ingest sang một runtime"); M1 "có thể mock". Gateway bị cấm nạp onnx. Hệ quả: search, E6, routing ở M3 đo trên vector giả; kết quả phải làm lại.
- **Sửa.** Đưa endpoint `/v1/embed` của sidecar (chỉ bge-m3) lên M1; guard/NER để M4.

#### N18 — Medium — Độ phức tạp vận hành vượt sức đội nhỏ nếu không gom lại
- Khoảng 15 service chạy lâu dài + migrate/seed; khoảng 30 secret (pepper, AUDIT_HMAC, khoá intent/approval, SIDECAR_TOKEN(+PREV), METRICS_TOKEN, 6 mật khẩu Redis, khoảng 10 role PG, 3 secret client Keycloak, CHAINLIT_AUTH_SECRET, khoá checkpoint có kid — 03 §8.4, khoá provider, API key). Không có bảng tổng hợp secret: ai sinh, ai đọc, chu kỳ xoay, cách xoay không downtime.
- **Kịch bản hỏng.** Xoay khoá intent không đúng thứ tự (signer chưa có pub mới) → mọi phê duyệt hỏng tới khi có người thức dậy xử lý.
- **Sửa.** Thêm bảng "secret inventory" vào 04; script `rotate.sh <secret>` cho từng loại; gom role PG/mật khẩu Redis sinh tự động từ một file seed.

#### N19 — Medium — DoD M4 về chi phí gần như tự đạt
- DoD M4 "giảm ≥50% chi phí tại iso-quality". Giá Haiku 5.5 $0.10/$0.50 so với Sonnet 5.5 $2/$10 (chênh 20×) → chỉ cần route khoảng 53% request sang Haiku là đạt, bất kể router có thông minh hay không.
- **Sửa.** DoD so với **baseline router ngẫu nhiên cùng tỉ lệ route** (đã có trong D10): router phải tốt hơn baseline về chất lượng tại cùng chi phí, CI không chồng.

#### N20 — Medium — "ASR thao tác ghi = 0%" vẫn còn trong DoD M5 / SOLUTION
- Mâu thuẫn với 04:1851(iii) và 04:1867 (approver naive, ASR > 0 là dự kiến). Câu "0%" chỉ đúng với approver oracle hoặc E4c. **Sửa:** ghi rõ "0/N với approver oracle (E4a-ii) và 100% từ chối đúng ở E4c".

#### N21 — Low — Tham chiếu lỗi thời
- ROADMAP:4 và SOLUTION:13 ghi "D0–D12" (thiếu D13/D14). ADR-001:15 và 04:528 vẫn ghi "access token của user" (trước D13). ADR-001 nhắc `ApprovalClient` trong khi 03 nói `SignerClient` không phải port. SOLUTION:36 và 00:146 còn tên CVE nguồn đơn (R25).

#### N22 — Low — Scope `tickets:write`
- 03 §6.1 dòng 688 "tickets:write chỉ cho execute_write", nhưng `prepare_*` cũng cần quyền ghi (đọc ticket để tính diff và ký). Sửa câu chữ để không ai cấp thiếu scope cho prepare.

#### N23 — Low — Endpoint evict của agent không định nghĩa xác thực
- `POST /v1/internal/evict?sub=` (03:718, 1031) không có mô tả auth → DoS (đẩy phiên người khác) nếu lộ ra mạng. Sửa: chỉ trên mạng nội bộ + token dịch vụ.

#### N24 — Low — Rate limit của signer in-memory khi chạy ≥2 replica
- 04:2323. Giới hạn thực tế nhân theo số replica. Sửa: rate limit bằng Redis hoặc chạy 1 replica (signer nhỏ, đủ tải).

#### N25 — Low — Giới hạn intent ≤8 KiB; cách viết ACL tickets
- Intent ≤8 KiB chặn mô tả/bình luận dài; cần thông báo lỗi rõ hoặc ký hash nội dung. ACL tickets ở 05 §6 liệt kê prefix con, 00 dùng `~mcp:tickets:*` (tương đương về hiệu lực, nên viết một kiểu).

#### N26 — Low — Tải M5 nặng với đội nhỏ
- M5 gom E4a (khoảng 7.600 lượt), user study 8–12 người (04 §13.2) và security suite. Khả thi nhưng chiếm nhiều lịch; nên tách user study sang song song M5–M6 với vòng thử 2 người ngay khi có thẻ B.

**Roadmap tổng thể.** M0 (4 spike + pilot, mỗi cái khoảng 2 ngày, có phương án B) khả thi. DoD M1–M2 đo được. DoD M4 cần sửa (N19), M5 cần sửa câu chữ (N20). Phụ thuộc sidecar của embedding cần kéo lên (N17).

---

## 3. Điều đáng giữ

- Intent do server tính và ký; `commit_intent` không nhận args; `expected_updated_at` nằm trong intent — thiết kế đúng hướng cho WYSIWYS và TOCTOU.
- Signer nhỏ, stateless, khoá tách khỏi UI và agent.
- `UNIQUE(intent_id)` làm lưới chống replay độc lập Redis; audit ghi cùng transaction với thay đổi nghiệp vụ.
- Bảng fault-injection F01–F30 / E4c chạy CI, không cần LLM.
- docs-mcp fail-closed với tài liệu class≥1 khi không ghi được taint (02:803).
- Tách policy-sidecar + `models.lock` + `MODELS_LOCK_SHA256`.
- Spike có phương án B; adapter `permissive` chỉ cho phép khi `ACME_ENV=eval` (04:1861).
- `TicketPolicy` vẫn đúng khi không có RLS; checkpoint mã hoá với AAD=thread_id.
- E4 tách ba phần, báo Wilson CI và quy tắc "ba" cho 0/N.

---

## 4. Kết luận

**Điểm: 7/10.**

**Phán quyết: cần sửa nhỏ trước khi code M0.** Kiến trúc đã đúng hướng và xử lý được phần lớn R01–R27. Các vấn đề High hầu hết là mâu thuẫn hợp đồng hoặc cấu hình trên giấy, sửa được bằng chỉnh tài liệu trong vài ngày. Mức "sửa lớn" chỉ xảy ra nếu spike C xác nhận Keycloak TE V2 không cho chat-ui exchange mà không làm hỏng D13; khi đó cần một phương án B cho D13 (vd signer tự xác thực user bằng phiên OIDC riêng của trang duyệt).

**Top 5 việc nên làm trước khi code:**
1. **D13 (N01, N02):** viết lại realm JSON đúng D13, đưa vào spike C việc xác minh luật "requester ∈ aud" của TE V2; sửa test 04:1068; F22/DoD M1/M5/E4c phải thử bằng chính token đăng nhập agent nhận được, và assert token đăng nhập không có `aud=approval-signer`.
2. **Hợp đồng intent (N05, N06, N07, N09):** thống nhất trong 00 việc lưu JWS, máy trạng thái `pending→committing→committed|failed` với CAS theo `jti`, ánh xạ UNIQUE violation → `approval_replayed`, thêm UNIQUE(intent_id) vào schema, chốt mã lỗi 403.
3. **Render an toàn (N03, N04, N10):** signer từ chối ký nếu có khoá của `args_canonical` không hiển thị; chặn ký tự bidi/điều khiển; verify khoá theo `(iss, kid)`.
4. **Taint (N12) và sidecar fail-closed (N15):** taint gắn `thread_id` + phòng ban, floor suy từ RLS; guard/NER fail-closed với nội dung tool/RAG và request ra provider ngoài.
5. **Vận hành và lịch (N17, N14, N18, N08, N19):** kéo `/v1/embed` lên M1; tách `AUDIT_HMAC_KEY` theo service; thêm bảng secret inventory + script xoay khoá; sửa mặc định classification ở 05/02; sửa DoD M4 so với baseline router.
