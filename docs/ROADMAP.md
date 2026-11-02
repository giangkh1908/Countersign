# Lộ trình (v2.1): Trợ lý AI nội bộ có trích dẫn kiểm chứng được và hành động qua MCP

> Phiên bản 2.1, 2026-11-01. Phạm vi theo [ADR-006](adr/ADR-006-scope-rag-citations.md) và [ADR-007](adr/ADR-007-actions-cache-observability.md). Lộ trình v1.3 (gateway đầy đủ, analytics, admin, hardening) xem git tag `backup/pre-prune-20261101`.
> Mỗi milestone kết thúc bằng bản chạy được, test xanh, đạt DoD đo được. Ký hiệu: **R** = reader, **W** = worker, **O** = orchestrator.
> Quy tắc vận hành: mặc định mỗi lúc một worker, phạm vi hẹp; chỉ chạy song song khi được yêu cầu và file không chồng nhau; review và merge xong mới giao việc phụ thuộc; backup trước mọi thay đổi trạng thái.

## Tổng quan

| Milestone | Chủ đề | Trạng thái |
|---|---|---|
| M0 | Spikes (identity, token exchange, checkpoint) | Xong |
| M1 | Walking skeleton trên compose | Xong |
| R0 | Thu gọn stack | Xong |
| R1 | Truy xuất thật + bộ đánh giá truy xuất | Xong (mặc định vector thuần; rerank đo trên dev, không giữ) |
| R2 | Câu trả lời có trích dẫn kiểm chứng được | Code xong; judge, κ và eval chờ LLM thật |
| A1 | Hành động qua MCP: ticket, báo cáo nhóm, phân quyền theo vai trò | Phần lớn; còn eval hành động, demo Telegram thật |
| Q1 | Cache và quan sát (log, trace, metric) | Xong với LLM mock: quan sát, exact cache (mặc định tắt) và số RQ4 trên stack thật; chờ LLM thật để đo độ trễ/chất lượng |
| R3 | An toàn: phân quyền, tài liệu độc, tấn công qua hành động | Corpus độc, harness ASR tầng hệ thống, canary, CI xong; ASR tầng LLM chờ LLM thật |
| R4 | Đánh giá tổng hợp, demo, báo cáo | |

## M1 — Walking skeleton (đã đạt phần lớn)

Đã có:
- compose khoẻ, `scripts/smoke.sh`;
- gateway ghi `usage_events`;
- E2E đóng ticket 56/56 trên stack thật (profile `tickets`);
- Playwright: đăng nhập thật qua BFF, chat mock, khẳng định không có token trong trình duyệt.

README chạy từ bản clone sạch trong 3 phút 44 giây (2026-11-02), smoke đạt ngay lần đầu, E2E 50/50. Lần đo có cache Docker và uv; chưa thử trên máy hoàn toàn mới, và chưa thử đăng nhập trình duyệt theo bước sửa file hosts.

## R0 — Thu gọn stack

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| ✅ (345f304) Đưa tickets-mcp + approval-signer vào profile `tickets`; agent chạy được khi không có ticket (router chỉ docs/direct) | W | `docker compose up` mặc định không có 2 service này; smoke xanh; `--profile tickets` + E2E đóng ticket vẫn xanh |
| ✅ Gỡ `depends_on` của agent → tickets-mcp và bff → approval-signer; xoá analytics-mcp, policy-sidecar, `GW_FEATURES`, `GW_SIDECAR_URL`, spikes, bench (dọn dẹp 2026-11-01) | W | Stack mặc định khoẻ khi không có tickets |
| ✅ Đo RAM/CPU: rảnh 1,2 GiB; khi chạy 20 câu hỏi qua luồng agent thật (có `search_documents`, kho đã ingest) đỉnh 1,26 GiB (bảng trong README) | W | Bảng số đo thật; mục tiêu < 2,5 GB lúc rảnh |
| ✅ Tắt `directAccessGrants` của client `admin-cli` trong realm `acme` (Keycloak tự tạo client này với grant bật; đã kiểm trên Keycloak thật) | W | Test realm: không client nào cho password grant |
| Cập nhật CLAUDE.md, SOLUTION theo ADR-006 | O | Xong (2026-10-30) |

**DoD R0:** compose mặc định chỉ gồm postgres, redis, keycloak, gateway, mock-provider, docs-mcp, agent, bff; smoke xanh; profile `tickets` vẫn xanh; bảng tài nguyên trong README.

## R1 — Truy xuất thật + bộ đánh giá truy xuất

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| ✅ (mặc định mock tất định `mock_hash`; embedding thật qua adapter `openai_compatible`, xem `models.ollama.yaml`) Gateway `/v1/embeddings` (OpenAI-compatible), thêm alias `acme-embed` vào `models.yaml` (hiện chỉ có `acme-fast`, `acme-smart`), port `EmbeddingProvider`, adapter provider thật + mock tất định; ghi `usage_events` | W | Test hợp đồng bằng SDK `openai`; leak-grep rỗng |
| Migration `chunks` theo đúng số chiều (bỏ cứng `vector(1024)`), thêm cột `article`, `clause`, `char_start`, `char_end` ✅ (đã thử: đổi `EMBED_DIM` khi có dữ liệu thì migrate dừng, trả về 1024 thì chạy lại được, dữ liệu nguyên vẹn). **Chọn model embedding thật: chưa làm** | W | Migration lên/xuống được; kiểm số chiều khi khởi động |
| ✅ docs-mcp: loader `vbpl_articles` (JSON Điều từ `data/vbpl`, cắt Điều dài theo khoản), gán `department`/`classification` theo nhóm như `data/SOURCES.md` (`python -m data.vbpl.metadata` sinh `documents.jsonl`) | W | 19 văn bản / 1.557 Điều nạp đủ; nạp lại ra cùng số chunk |
| ✅ docs-mcp: embedder qua gateway (`gateway_http`, compose mặc định); ingest 19 văn bản luật (2.003 chunk) + 30 tài liệu ACME (69 chunk); ingest lần hai bỏ qua hết; offset khớp trên cả 2.003 chunk luật. Đã ingest lại bằng `bge-m3` chạy local (Ollama) không dùng `--force`: 2.072 chunk, ~20 phút trên GTX 1650 4 GB, ingest lần hai bỏ qua hết; `index_sig` và `index_meta.embed_model` dùng id model thật | W | Ingest lặp lại được; số chunk khớp |
| ✅ 150 câu (40 viết sau khi đọc Điều đúng, 110 viết mù; nhãn mức Điều, chưa có khoản) Bộ câu hỏi có nhãn ~150 câu trên corpus luật: nhãn vàng (văn bản, Điều); loại câu (tra cứu, tổng hợp nhiều Điều/luật, không có câu trả lời); câu hỏi viết theo giọng nhân viên, không chép lời luật. 110 câu mới viết khi chưa mở nội dung corpus (file `vbpl-v1.phase1.jsonl`, đóng băng), rồi mới gán nhãn bằng đọc/grep corpus thô, không dùng retriever | W + O duyệt mẫu | Kiểm tay 100% nhãn (còn 34 nhãn đánh dấu chưa chắc, người duyệt xem trước); phân bố theo nhóm, loại câu, split in bởi `validate` |
| (Phụ) Chạy cùng script đánh giá trên Zalo legal (corpus riêng) làm benchmark ngoài | W | Có số recall@k để so với công bố khác |
| ✅ trừ rerank: Hybrid search: pgvector + Postgres full-text (tiếng Việt bỏ dấu/không bỏ dấu), trộn RRF; rerank tuỳ chọn qua gateway; tra trực tiếp khi câu hỏi nêu số Điều/số hiệu | W | Bật/tắt từng thành phần bằng config |
| ✅ trừ rerank (đã chạy thật 5 cấu hình trên 40 câu, xem dưới): Script đánh giá truy xuất: recall@k, MRR, nDCG theo loại câu; so 4 cấu hình (vector, BM25, hybrid, hybrid+rerank) | W | Bảng kết quả có seed, phiên bản, chi phí |

**Chốt cấu hình trên dev (2026-11-02, trước khi chạy test):** dev 81 câu có đáp án, `retrieval_k` 14, `n_cand` 70 như docs-mcp thật, bootstrap 95%, Δ theo cặp so với vector.

| Cấu hình | recall@5 | Δ recall@5 | MRR | Δ MRR |
|---|---|---|---|---|
| vector | 0,891 [0,829; 0,947] | 0 | 0,843 | 0 |
| hybrid w=1 | 0,545 | -0,346 [-0,451; -0,253] | 0,481 | -0,362 [-0,452; -0,263] |
| hybrid w=0,25 | 0,774 | -0,117 [-0,191; -0,049] | 0,674 | -0,170 [-0,251; -0,087] |
| hybrid w=0,1 | 0,897 | +0,006 [0,000; +0,019] | 0,776 | -0,067 [-0,125; -0,009] |
| `ts_rank` + w=0,1 | 0,891 | 0,000 [-0,019; +0,019] | 0,733 | -0,111 [-0,169; -0,054] |
| ghim + w=0,1 | 0,897 | +0,006 [0,000; +0,019] | 0,806 | -0,037 [-0,089; +0,014] |

Đủ 17 cấu hình ở `eval/results/rag/20261102T071619/report.json`. Không cấu hình hybrid nào hơn vector một cách phân biệt được; mọi hybrid trừ ghim + w=0,1 có MRR thấp hơn vector rõ rệt. Chẩn đoán: 30 câu vector đúng mà hybrid w=1 sai, 16 do FTS xếp chunk đúng thấp, 14 do chunk sai có mặt ở cả hai nhánh nên được RRF cộng điểm.

**Quyết định:** mặc định **vector thuần** (`DOCS_USE_FTS=false`, `DOCS_DIRECT_LOOKUP=off`): MRR cao nhất, nhanh nhất (p50 ~232 ms so với 245–330 ms), ít thành phần nhất. Hybrid và ghim giữ làm công tắc nghiên cứu. Cấu hình so sánh khi chạy test: `hybrid_direct@wfts0.1`. Test chạy một lần cho đúng hai cấu hình này, không chỉnh lại theo kết quả test.

Hạn chế: dev có 40 câu `read_first` sát từ vựng luật; chỉ 10 câu nêu số Điều nên ghim chưa được đo đủ; w < 0,1 chưa đo.

**Kết quả test (chạy một lần, 2026-11-02, `eval/results/rag/20261102T072218/report.json`):** 49 câu có đáp án, toàn bộ viết mù.

| Cấu hình | recall@5 | recall@10 | MRR | p50 |
|---|---|---|---|---|
| vector (mặc định) | 0,619 [0,497; 0,735] | 0,765 | 0,566 | 230 ms |
| `hybrid_direct@wfts0.1` | 0,662 [0,549; 0,777] | 0,769 | 0,584 | 325 ms |

Δ theo cặp so với vector: recall@5 +0,043 [-0,039; +0,138], MRR +0,018 [-0,053; +0,093], không phân biệt được. Quyết định giữ nguyên. Tách theo loại câu: tra cứu recall@5 0,692, tổng hợp thấp hơn nhiều.

Điểm test thấp hơn dev khoảng 0,27 recall@5. Phần lớn chênh lệch đến từ cách viết câu: dev có 40 câu `read_first` sát từ vựng luật, test toàn câu viết mù. Con số đại diện cho người dùng thật là số test. Khoảng cách này đủ lớn để thử rerank (mục rerank ở trên) và để đo lại hybrid với câu hỏi viết mù. Muốn đo lại phải có tập test mới, không dùng lại tập này để chỉnh.

**Rerank trên dev (2026-11-02, `eval/results/rag/20261102T083952/`):** bge-reranker-v2-m3 Q8_0 qua `llama-server` b11721 (Vulkan, GTX 1650), gateway `/v1/rerank`, nền vector thuần, 81 câu chấm điểm. Baseline khớp số cũ.

| Cấu hình | recall@5 | MRR | nDCG@10 | p50 mỗi truy vấn | Δ recall@5 [CI95] | Δ MRR [CI95] |
|---|---|---|---|---|---|---|
| vector | 0,891 | 0,843 | 0,840 | 0,24 s | | |
| rerank top20 | 0,872 | 0,861 | 0,854 | 3,0 s | −0,019 [−0,068; +0,031] | +0,018 [−0,030; +0,069] |
| rerank top30 | 0,883 | 0,870 | 0,861 | 4,3 s | −0,008 [−0,058; +0,039] | +0,027 [−0,026; +0,085] |
| rerank top50 | 0,883 | 0,866 | 0,860 | 6,9 s | −0,008 [−0,058; +0,039] | +0,023 [−0,032; +0,082] |

Không cấu hình nào phân biệt được với vector; câu tổng hợp (13 câu) recall@5 tăng 0,551 → 0,615 ở top30 nhưng mẫu quá nhỏ. Rerank thêm 3–7 s mỗi truy vấn trên GPU này. Quyết định: giữ `DOCS_RERANK=none`; không chạy tập test cho rerank (theo quy tắc trên, cần tập test mới). Qwen3-Reranker-0.6B chạy được (llama-server trả điểm đúng trên câu thử) nhưng lượt đo bị dừng vì máy thiếu RAM, chưa có số.

**DoD R1:** có bảng recall@5/@10 và MRR cho 4 cấu hình trên ~150 câu. Cấu hình mặc định được chọn theo số đo, không theo cảm tính. Toàn bộ chạy lại được bằng một lệnh.

**Khung đánh giá truy xuất (đã chạy thật trên index bge-m3, 40 câu):** `eval/rag/` có chỉ số (recall@k, hit@k, MRR, nDCG@10; hàm thuần, có test), định dạng `vbpl-v1.jsonl` kèm trình kiểm nhãn so với `data/raw/vbpl`, và script chạy 5 cấu hình (vector, FTS `unaccent`, FTS tách từ `segmented`, hybrid, hybrid + tra trực tiếp) qua port `DocumentRetriever`. Cấu hình `hybrid_direct` dùng chung `ArticlePinner` với `DocumentService`. Mới có 40/150 câu (đều loại tra cứu, đủ 19 văn bản; 10 câu nêu số Điều); các câu tổng hợp và câu không có đáp án làm ở đợt sau. Cấu hình `hybrid_rerank` chưa làm; khoảng tin cậy bootstrap đã có (xem dưới). Báo cáo JSON ghi `index_sig`, model, chiều embedding vào `eval/results/rag/<run_id>/report.json` (đã gitignore).

**Kết quả lần chạy 2026-11-02 với embedding thật (40 câu, Điều là đơn vị chấm, index 2.003 chunk luật + 69 chunk ACME, `embed_model` = `bge-m3` 1024 chiều chạy local):**

| Cấu hình | recall@5 | recall@10 | hit@5 | MRR | nDCG@10 | p50 ms |
|---|---|---|---|---|---|---|
| chỉ vector (bge-m3) | 0,975 | 0,988 | 0,975 | 0,924 | 0,940 | 200 |
| chỉ FTS (`unaccent`) | 0,287 | 0,438 | 0,300 | 0,184 | 0,242 | 119 |
| chỉ FTS (tách từ, `segmented`) | 0,312 | 0,362 | 0,325 | 0,203 | 0,238 | 260 |
| hybrid (RRF, bge-m3) | 0,537 | 0,688 | 0,550 | 0,516 | 0,552 | 307 |
| hybrid + tra trực tiếp (bge-m3) | 0,637 | 0,762 | 0,650 | 0,613 | 0,645 | 310 |

**Đây là số thật trên 40 câu (đều loại tra cứu), chưa phải bộ 150 câu; khoảng tin cậy ở bảng dưới, chưa có rerank, chưa chọn cấu hình mặc định.** Báo cáo JSON ghi `embed_model` thật (`bge-m3`); `index_sig` ghi `unknown` vì lần chạy không truyền `--index-sig`. Trước đó bảng này chạy trên vector `mock_hash` nên các hàng vector không có giá trị. Điều quan sát được: ở mẫu này vector đứng đầu và FTS kéo hybrid xuống thấp hơn vector (truy vấn OR các từ của câu hỏi, `ts_rank_cd`, không loại từ dừng; việc sửa nhánh FTS chưa làm). Tra trực tiếp: trên 10 câu nêu số Điều, recall@5 là 1,000 (hybrid + tra trực tiếp và vector) so với 0,600 của hybrid; trên 30 câu còn lại hybrid và hybrid + tra trực tiếp bằng nhau (0,517), vector 0,967. Mỗi hàng chỉ chênh vài câu nên chưa kết luận chắc về `segmented` so với `unaccent`. Việc còn lại: bộ 150 câu, rerank, quyết định sửa FTS/RRF, rồi mới chọn cấu hình mặc định.

**Chẩn đoán hybrid và thử có kiểm soát nhánh FTS/RRF (2026-11-02, cùng 40 câu, cùng index; chưa đổi mặc định nào):** mỗi dòng là một cấu hình riêng, đổi đúng một thứ so với dòng gốc (hậu tố `@...` trong `eval/rag/backends.py`). Mặc định của mọi công tắc mới giữ hành vi cũ (`DOCS_RRF_WEIGHT_FTS=1.0`, `DOCS_FTS_STOPWORDS=false`, `DOCS_FTS_RANK=cd`, `DOCS_FTS_TITLE=false`). Khoảng là bootstrap 95% theo câu hỏi (1.000 lần, seed 42); Δ là chênh theo cặp so với hybrid gốc.

| Cấu hình | recall@5 [CI95] | recall@10 | MRR | Δ recall@5 so với hybrid [CI95] |
|---|---|---|---|---|
| chỉ vector | 0,975 [0,925; 1,000] | 0,988 | 0,924 | +0,438 [+0,275; +0,600] |
| chỉ FTS (`ts_rank_cd`, gốc) | 0,287 [0,163; 0,425] | 0,438 | 0,184 | -0,250 [-0,375; -0,125] |
| chỉ FTS + từ dừng | 0,263 [0,138; 0,400] | 0,438 | 0,164 | -0,275 [-0,400; -0,125] |
| chỉ FTS + `ts_rank` | 0,525 [0,375; 0,675] | 0,588 | 0,398 | -0,013 [-0,150; +0,125] |
| chỉ FTS + tiêu đề (A) | 0,338 [0,200; 0,500] | 0,463 | 0,194 | -0,200 [-0,325; -0,075] |
| hybrid gốc (w=1, `n_cand` 250) | 0,537 [0,375; 0,700] | 0,688 | 0,516 | 0 |
| hybrid, `n_cand`=50 / 70 | 0,613 / 0,562 | 0,887 / 0,762 | 0,545 / 0,528 | +0,075 [0,000; +0,175] / +0,025 [0,000; +0,075] |
| hybrid, trọng số FTS 0,5 | 0,738 [0,600; 0,875] | 0,863 | 0,592 | +0,200 [+0,075; +0,325] |
| hybrid, trọng số FTS 0,25 | 0,863 [0,738; 0,963] | 0,988 | 0,673 | +0,325 [+0,200; +0,475] |
| hybrid, trọng số FTS 0,1 | 0,988 [0,963; 1,000] | 0,988 | 0,792 | +0,450 [+0,275; +0,600] |
| hybrid + từ dừng | 0,662 [0,512; 0,800] | 0,738 | 0,513 | +0,125 [+0,025; +0,250] |
| hybrid + `ts_rank` | 0,762 [0,637; 0,887] | 0,887 | 0,694 | +0,225 [+0,075; +0,400] |
| hybrid + tiêu đề (A) | 0,562 [0,412; 0,725] | 0,762 | 0,537 | +0,025 [0,000; +0,075] |
| hybrid + từ dừng + w=0,25 (ghép hai thay đổi) | 0,887 [0,787; 0,975] | 0,988 | 0,724 | +0,350 [+0,225; +0,500] |
| hybrid + tra trực tiếp (gốc) | 0,637 [0,487; 0,775] | 0,762 | 0,613 | +0,100 [+0,025; +0,200] |
| hybrid + tra trực tiếp, w=0,25 | 0,938 [0,863; 1,000] | 0,988 | 0,755 | +0,400 [+0,250; +0,575] |
| hybrid + tra trực tiếp, w=0,1 | 0,988 [0,963; 1,000] | 0,988 | 0,852 | +0,450 [+0,275; +0,600] |
| hybrid + tra trực tiếp + từ dừng + w=0,25 | 0,963 [0,900; 1,000] | 0,988 | 0,806 | +0,425 [+0,275; +0,575] |

Chạy lại: `uv run --all-packages python -m eval.rag run --suite vbpl-v1 --configs sweep`, rồi `... python -m eval.rag compare <report.json> --baseline hybrid --select hybrid@wfts0.5,hybrid@wfts0.25,hybrid@wfts0.1` và `... python -m eval.rag diagnose --suite vbpl-v1`. Còn các dòng `hybrid_direct` với `wfts0.5`, `stop`, `rank`, `title` trong báo cáo JSON (`--configs sweep`). So với vector: không cấu hình hybrid nào có recall@5 cao hơn vector một cách phân biệt được (w=0,1 chênh +0,013, khoảng [0,000; +0,037]); MRR của mọi hybrid vẫn thấp hơn vector (w=0,1: 0,792 so với 0,924, Δ [-0,219; -0,054]).

*Chẩn đoán (`python -m eval.rag diagnose`, `n_cand`=250 như eval):* vector đúng ở top-5 trên 39/40 câu, hybrid trên 22/40. Có 18 câu vector đúng mà hybrid sai (1 câu ngược lại). Trong 18 câu đó, chunk đúng đứng hạng 1 hoặc 2 ở nhánh vector (cả 18 câu). Chia theo cơ chế: 9 câu chunk đúng không có trong nhánh FTS và bị chen bởi chunk có mặt ở cả hai nhánh dù vector xếp thấp hơn (đúng cơ chế giả thuyết); 9 câu chunk đúng có trong FTS nhưng ở hạng 27 đến 175 và bị chen theo cùng kiểu (cơ chế gần giống, nguyên nhân là FTS xếp chunk đúng thấp, không phải vắng mặt); 0 câu nguyên nhân khác. Mọi chunk chen (5 chunk đứng trên chunk đúng ở mỗi câu, 90 chunk) đều có điểm RRF ≥ 1/61 và đều có mặt ở cả hai nhánh, nhưng không phải "hạng thấp ở cả hai danh sách": trung vị hạng vector 12,5 và hạng FTS 10; 78/90 chunk có cả hai hạng ≤ 60. Chỉ cần hạng ở cả hai nhánh trong khoảng 60 là đủ vượt chunk đứng đầu của một nhánh. Chi tiết lệch với giả thuyết: eval chạy `n_cand`=250 (`5*pool`), docs-mcp thật dùng 70, không phải 50; `n_cand` nhỏ chỉ giúp ít (0,613 và 0,562 so với 0,537, khoảng chưa phân biệt được). Tính lại offline từ hạng đã có: nếu trọng số FTS là 0,5 / 0,25 / 0,1 thì 8 / 13 / 18 trong 18 câu sai được cứu, khớp với bảng đo thật.

*Trùng từ câu hỏi và Điều đúng (vector 0,975 có lạc quan không):* trên 40 câu, trung bình 74,9% từ nội dung khác nhau của câu hỏi (sau khi bỏ từ dừng) xuất hiện trong Điều đúng (trung vị 77,8%), so với 23,4% với Điều ngẫu nhiên; 38/40 câu đạt từ 50%. 55,9% cặp từ liền nhau (không phải từ dừng) của câu hỏi có trong Điều đúng, chỉ 2 câu bằng 0. Bộ xếp hạng trùng từ thuần Python có trọng số IDF đạt recall@5 0,625 [0,475; 0,775]. Nghĩa là câu hỏi khá gần từ vựng của Điều, nên 0,975 của vector có thể phản ánh bộ câu dễ hơn câu hỏi nhân viên thực, và FTS có lẽ nên mạnh hơn khi diễn đạt đúng từ luật. Con số này chưa chứng minh chiều ngược lại: trùng từ cao nhưng FTS Postgres (OR toàn bộ từ) vẫn chỉ đạt 0,287, nên chất lượng nhánh FTS là vấn đề riêng, không chỉ do bộ câu.

*Giới hạn:* trọng số FTS 0,1 là mép dưới của lưới {0,5; 0,25; 0,1} và điểm tăng đơn điệu khi giảm, tức tối ưu có thể nằm ngoài lưới hoặc đúng bằng "gần như chỉ vector"; chọn đôi nửa bộ (chọn trên câu chẵn, đo trên câu lẻ và ngược lại) đều chọn 0,1 và giữ 0,975 và 1,000, nhưng 20 câu mỗi nửa là quá ít để coi là kiểm chứng độc lập. Danh sách từ dừng chọn trước theo loại từ, không chỉnh theo bộ này, và `title` chỉ ghép ở phía truy vấn (không đổi migration, mất chỉ mục GIN của `tsv` trong biến thể này). Chưa có đề xuất nào được áp dụng làm mặc định.

Lệnh (máy không có `make` thì chạy dòng `uv run` tương đương; corpus thô ở `data/raw/vbpl` hoặc đặt `VBPL_RAW_DIR`):

| Việc | `make` | Tương đương |
|---|---|---|
| Kiểm nhãn | `make eval-rag-validate` | `uv run --all-packages python -m eval.rag validate --suite vbpl-v1` |
| Chạy với retriever giả (kiểm mạch, số vô nghĩa) | `make eval-rag-fake` | `uv run --all-packages python -m eval.rag run --suite vbpl-v1 --fake` |
| Chạy thật (cần Postgres đã ingest; chạy từ máy có thể nối tới Postgres và gateway) | `make eval-rag` | `uv run --all-packages python -m eval.rag run --suite vbpl-v1 --index-sig <sig>` |

**Bộ 150 câu và quy tắc dev/test (2026-11-02).** Mỗi câu có `split` (`dev`/`test`) và `authoring` (`read_first`/`blind`). 40 câu cũ: `dev`, `read_first` (viết sau khi đọc Điều đúng, từ vựng sát luật nên số đo lạc quan). 110 câu mới: `blind` (viết trước khi mở nội dung corpus, chỉ biết tên 19 văn bản), chia phân tầng theo loại × nhóm với seed cố định thành 50 `dev` và 60 `test`. Tổng: dev 90, test 60; tra cứu 101, tổng hợp 29, không có đáp án 20. Câu không đáp án không tính recall, `run` báo riêng (`n_unanswerable`). `names_article` là false cho cả 110 câu mới (không câu nào nêu số Điều), nên cấu hình tra trực tiếp chỉ còn được đo trên 10 câu cũ có nêu Điều.

**Chỉ chỉnh cấu hình trên dev; chạy test đúng một lần ở cuối.** `run --split dev` là mặc định; `--split test` phải gõ rõ và in cảnh báo. `diagnose` chỉ nhìn dev. Chọn trọng số FTS, từ dừng, `n_cand`, cấu hình ghim... đều bằng dev; sau khi khoá cấu hình mới chạy `--split test`, không quay lại chỉnh theo kết quả test.

**Sửa `n_cand` (eval 250, docs-mcp thật 70).** `run` không còn ghi đè `docs_n_cand` và không còn lấy `k` = 50. `k` được đọc bằng cách dựng `DocumentService` thật (cùng `docs_max_per_doc` của Settings), gọi `search` với `top_k` mặc định rồi ghi lại `k` mà retriever nhận (`backends.service_retrieval_k`); `n_cand` do adapter pgvector tự suy ra từ `k` đó, đúng như khi chạy thật. Hệ quả: eval chỉ có chừng ấy chunk (đã gộp theo Điều rồi cắt 10) nên `recall@10` bị chặn bởi số chunk docs-mcp trả ở `top_k`=5; số mới không so trực tiếp được với số cũ (40 câu, pool 50, `n_cand` 250). `k` thật và `docs_n_cand` ghi trong `report.json` (`dataset.retrieval_k`, `dataset.docs_n_cand`). Các hậu tố `nc50/nc70/nc250` chỉ còn để thử độ nhạy.

Chạy thật cần `Settings` của docs-mcp có `DOCS_USE_VECTOR`, `DOCS_USE_FTS`, `DOCS_DIRECT_LOOKUP` (`off|pin`), `DOCS_FTS_MODE`; thiếu thì script dừng và báo rõ, không chạy nhầm cấu hình. Eval đi qua cùng ACL với một `Principal` đọc được toàn bộ corpus luật (`eval_principal()` trong `eval/rag/fakes.py`, chỉ dùng cho đánh giá).

## R2 — Câu trả lời có trích dẫn kiểm chứng được

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| ✅ Định dạng trả lời: mỗi câu có mã trích `[n]` trỏ tới đoạn cụ thể (văn bản, Điều, khoản, vị trí ký tự); agent chỉ được trích đoạn đã truy xuất | W | Test: trích nguồn ngoài danh sách bị loại |
| ✅ code, chưa chạy với judge thật: Bộ kiểm chứng sau sinh: tách câu → kiểm từng câu có được đoạn trích hỗ trợ (LLM-judge, JSON có cấu trúc; thêm alias `acme-judge` vào `models.yaml`); câu không được hỗ trợ bị gắn cờ hoặc bỏ; không đủ nguồn thì trả lời "không tìm thấy trong tài liệu" | W | Bật/tắt bằng config; đo được chi phí và độ trễ thêm |
| ✅ Vitest + Playwright (4/4 spec xanh trên stack; citations.spec giả BFF bằng page.route nên không cần LLM sinh `[#id]`): UI: bấm `[n]` mở đoạn nguồn, tô đúng câu được trích; hiển thị câu bị gắn cờ "chưa kiểm chứng" | W | Vitest + Playwright |
| Hiệu chuẩn judge: 30–50 câu chấm tay, Cohen's κ người–judge | O + R | Báo cáo κ |
| Đánh giá: citation precision/recall, faithfulness, tỉ lệ từ chối đúng với câu không có đáp án; có và không có bộ kiểm chứng | W | Bảng so sánh kèm chi phí/câu và độ trễ p50/p95 |

**DoD R2:** báo cáo được mức cải thiện của bộ kiểm chứng (citation precision, faithfulness) kèm khoảng tin cậy và chi phí. Câu hỏi không có đáp án trong tài liệu được từ chối đúng ở mức đo được.

## A1 — Hành động qua MCP và phân quyền theo vai trò

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| ✅ Ma trận quyền vai trò × tool × kênh (dự thảo ở ADR-007), thực thi ở MCP server | O + W | Test mọi ô của ma trận, cả cho phép lẫn từ chối |
| ✅ unit/integration + E2E tạo ticket trên stack (`scripts/e2e-create-ticket.sh`, 30/30 assertion: duyệt, từ chối, replay, admin/auditor bị chặn, vượt clearance): tickets-mcp: `prepare_create_ticket` qua intent + phê duyệt ký số; router agent thêm nhánh tạo ticket | W | E2E tạo ticket xanh; từ chối thì không ghi gì |
| ✅ `notify-mcp`: port `MessageChannel`, adapter `telegram` + `fake`, tool `prepare_send_group_report`, bí danh kênh, mức mật theo kênh, profile `notify` | W | E2E gửi qua `fake`; chat ID tuỳ ý bị từ chối; dữ liệu vượt mức mật bị chặn; leak-grep rỗng. Đã đạt: `bash scripts/e2e-notify.sh` 30/30 assertion, 45 giây (gửi đủ luồng duyệt, replay, kênh tuỳ ý, kênh phòng khác, taint, vai trò chặn) |
| Eval hành động: chọn đúng tool và tham số, từ chối đúng khi thiếu quyền, không hành động khi chỉ hỏi | W | Bảng kết quả theo vai trò, chạy lại bằng một lệnh |
| ✅ Đo RAM khi bật `tickets` + `notify` (+ `obs`): 1,95 GiB rảnh, notify-mcp 93 MiB (bảng trong README) | W | Bảng số đo thật trong README |

**DoD A1:** user tạo ticket và gửi báo cáo Telegram qua chat, có thẻ duyệt; ma trận quyền có test đầy đủ; thêm kênh mới chỉ là thêm file adapter.

## Q1 — Cache và quan sát

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| ✅ code, test và đã chạy trên stack (profile `cache`, `GW_CACHE_ADAPTER=redis`, mặc định tắt) Exact cache (service `redis-cache`): khoá gồm model, prompt, phạm vi quyền; không cache thao tác ghi; giữ nguyên trích dẫn đã kiểm chứng | W | Test: khác phạm vi quyền thì không trúng cache |
| ✅ đo trên stack thật, LLM mock (`python -m eval.cache users|run|report|scan`; hit rate 12,5% đến 42,5% ở lặp 20%/50%, đường hit 3 đến 9 ms, 28 thăm dò chéo phạm vi trúng 0; số trong `cache-observability.md`). Chưa đo chất lượng RAG qua cache và độ trễ với LLM thật. Đánh giá RQ4: hit rate, chi phí, độ trễ, chất lượng khi có/không cache; semantic cache ở dạng thử nghiệm, kèm đo rò rỉ | W | Bảng so sánh; semantic cache mặc định vẫn tắt |
| ✅ (Tempo) OpenTelemetry xuyên BFF → agent → gateway → MCP; chọn backend trace nhẹ ở profile `obs` | W | Một câu hỏi cho ra một trace đủ các hop |
| ✅ trừ phần cache: Log JSON có `trace_id`; dashboard Grafana: truy xuất, chi phí, cache, hành động | W | Dashboard chạy trên số thật |
| ✅ (`python -m eval.canary` xanh) Trace và log không chứa nội dung prompt/tài liệu | W | Quét canary trên trace = 0 |

**DoD Q1:** có báo cáo RQ4; từ một câu hỏi lần ra được toàn bộ đường đi, chi phí và độ trễ từng hop.

## R3 — An toàn

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| ✅ phần không cache (`scripts/e2e-leak-check.sh`: 16 user, ~61 truy vấn docs-mcp + 5 lượt agent mỗi user, 0 rò rỉ ở search, SSE, trích dẫn, lịch sử; LLM là mock) và phần cache (cache bật, chạy hai lần liên tiếp: 0 rò rỉ cả hai, lượt 2 có 76 hit; `python -m eval.cache scan` quét 651 khoá redis-cache, 0 dấu vết trái quyền; đối chứng dương trong Redis chưa có vì mock không chép tài liệu) Kiểm tra rò rỉ: mỗi user trong 16 user hỏi bộ câu chạm tài liệu trái quyền; kiểm cả câu trả lời, trích dẫn, cache | W | 0 tài liệu trái quyền xuất hiện ở bất kỳ đâu |
| ✅ Tấn công qua hành động (mock LLM chiếm hoàn toàn, 13 cấu hình lớp, `python -m eval.attack`; ASR tầng LLM chưa đo): tài liệu độc lừa agent tạo ticket hoặc gửi dữ liệu mật vào nhóm (dùng adapter `fake`) | W | Bảng ASR có/không từng lớp (phê duyệt, mức mật kênh, taint) |
| ✅ corpus (71 tài liệu: 56 độc = 8 kỹ thuật × 7, 5 mật có canary, 10 sạch; ground truth `manifest.jsonl`; nạp: `scripts/ingest-attack-corpus.sh`, chưa nạp vào stack), chưa đo ASR tầng LLM: Xây corpus độc và nạp vào kho; đo tỉ lệ tấn công thành công (ASR) có/không spotlighting và bộ kiểm chứng | W | Bảng ASR theo kỹ thuật |
| ✅ trong-process (16 user × mọi truy vấn, kể cả retriever rò ACL; stack thật do E2E): Canary trong tài liệu mật không bao giờ ra khỏi phạm vi quyền (log, response, usage) | W | Quét tự động = 0 |
| ✅ job `security` (`pytest -m security` + `eval.attack --quick --check`): Security regression chạy trong CI | W | CI fail khi hồi quy |

**DoD R3:** rò rỉ trái quyền = 0 trên toàn bộ ca thử; có bảng ASR theo kỹ thuật injection, kèm số đo ảnh hưởng của từng lớp phòng thủ.

## R4 — Đánh giá tổng hợp, demo, báo cáo

| Việc | Agent | Tiêu chí xong |
|---|---|---|
| Ablation: bỏ từng thành phần (hybrid, rerank, kiểm chứng, spotlighting) → ảnh hưởng chất lượng, an toàn, chi phí | W | Bảng + biểu đồ |
| Chạy với ≥ 2 model thật (một rẻ, một mạnh) trong ngân sách cố định | W + O | Ngân sách và chi phí thực ghi rõ |
| Demo Playwright: đăng nhập → hỏi → câu trả lời có trích dẫn → mở nguồn; user khác phòng không thấy tài liệu mật; tạo ticket và báo cáo nhóm có thẻ duyệt | W | Xanh trên compose |
| Bản deploy gọn: VPS 4 GB, reverse proxy + HTTPS, hướng dẫn | W | Chạy được trên VPS thật |
| Báo cáo: phương pháp, số liệu, giới hạn, công bố seed/prompt/phiên bản | O + R | Hoàn chỉnh |

**DoD R4:** mọi số liệu trong báo cáo tái lập được bằng script trong repo; demo chạy trên VPS 4 GB.

## Ngoài phạm vi (đóng băng hoặc bỏ)

| Hạng mục | Tình trạng |
|---|---|
| analytics-mcp | Đã xoá (dọn dẹp 2026-11-01) |
| policy-sidecar (guard, NER) | Đã xoá (dọn dẹp 2026-11-01) |
| Rate limit, budget đầy đủ, fallback nhiều provider, router chi phí | Bỏ (chỉ giữ ghi usage + chi phí) |
| Trang admin, i18n, HA, mTLS, Helm, secret manager | Bỏ |
