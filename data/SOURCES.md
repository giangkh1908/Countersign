# Nguồn dữ liệu thật

Phạm vi: [ADR-006](../docs/adr/ADR-006-scope-rag-citations.md). Dữ liệu thô nằm ở `data/raw/` (đã gitignore, không commit).
Chỉ commit công cụ tải, danh sách chọn và manifest checksum. Kiểm tra lần cuối: 2026-10-30.

## 1. Corpus chính: luật Việt Nam từ CSDL quốc gia về pháp luật (vbpl.vn)

| | |
|---|---|
| Nguồn | https://vbpl.vn (Bộ Tư pháp), trang toàn văn từng văn bản |
| Pháp lý | Văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả (Luật SHTT 50/2005/QH11, Điều 15) |
| Danh sách | `data/vbpl/selection.json`: 19 luật/bộ luật, 4 nhóm `hr`, `finance`, `it`, `legal` |
| Lệnh | `uv run --with beautifulsoup4 python -m data.vbpl` → `data/raw/vbpl/` (khoảng 1 phút, nghỉ 3 s giữa các request) |
| Kết quả | 1.557 Điều, khoảng 1,82 triệu ký tự; mỗi Điều có số, tiêu đề, chương, các khoản |
| Kiểm chứng | Số Điều từng luật liên tục từ 1 đến N, không thiếu; khớp số Điều thật (BLLĐ 220, Doanh nghiệp 218, SHTT 222, Kế toán 74, PCTN 96) |

Đơn vị trích dẫn là **Điều** (`doc_num` + số Điều + khoản), đúng cách người dùng trích luật ngoài đời.

Nhóm → phòng ban/cấp mật của ACME (gán tất định, ghi rõ là **giả lập**, vì văn bản luật vốn công khai):

| Nhóm | Văn bản | `department` | `classification` |
|---|---|---|---|
| `hr` | BLLĐ 2019, Việc làm 2025, ATVSLĐ 2015, BHXH 2024, Công đoàn 2024, Bình đẳng giới 2006 | `HR` | c1 |
| `it` | An ninh mạng 2025, BV dữ liệu cá nhân 2025, Giao dịch điện tử 2023, Dữ liệu 2024, ATTT mạng 2015 | `IT` | c1 |
| `finance` | Kế toán 2015, Thuế TNDN 2025, Thuế GTGT 2024, Thuế TNCN 2025, Quản lý thuế 2025 | `ALL` | c0 |
| `legal` | Doanh nghiệp 2020, SHTT 2005, Phòng chống tham nhũng 2018 | `ALL` | c0 |

Realm hiện không có phòng tài chính, nên `finance` và `legal` để `ALL`. Tài liệu mật thật sự (c2/c3, có canary) vẫn là tài liệu
ACME tổng hợp do `data/generator` sinh; chúng dùng cho kiểm tra rò rỉ trái quyền.

## 2. Đã tải nhưng KHÔNG dùng làm corpus: UTS_VLC

| | |
|---|---|
| Nguồn | `undertheseanlp/UTS_VLC` (Hugging Face), MIT |
| Lệnh | `HF_HUB_DISABLE_XET=1 hf download undertheseanlp/UTS_VLC --repo-type dataset --local-dir data/raw/uts_vlc` |
| sha256 | `data/2026_01-00000-of-00001.parquet` `334f08ef06d09f2ab47827f353936c0b8d47ce994fe143792b9a80840f07e404`; `database/vn_law.sqlite` `6bb9c82e09b13240bff943ae2e70c499f7b61ee34739ec4d1371f1eaf8c649c2` |

**Lý do loại:** ở split 2026_01 có 158/318 dòng mà số hiệu ở đầu văn bản không khớp với số hiệu trong thân văn bản. Ví dụ dòng
"Bộ luật Lao động" chứa một kế hoạch của UBND tỉnh Lào Cai, dòng "Luật Việc làm" chứa Luật Dân số 2025. Các split 2021/2023 lệch
toàn bộ theo cùng phép kiểm. Chỉ dùng `vn_law.sqlite` (metadata: số hiệu, tình trạng hiệu lực, link vbpl.vn) để chọn văn bản.

## 3. Bộ đánh giá phụ (chỉ dùng nội bộ, chưa rõ giấy phép)

| Bộ | Nguồn | Giấy phép | sha256 | Dùng cho |
|---|---|---|---|---|
| Zalo AI Legal Text Retrieval | `GreenNode/zalo-ai-legal-text-retrieval-vn` | Không nhất quán (thẻ ghi MIT, mô tả ghi CC-BY-4.0) | corpus `b5eb3a054bd29561822b996a1c3207a597ede1aa6e286b9c11876de264c48351`, queries `7cf566b867fbd5cd6428058dea1115593c08c4b0ce0d7b0b00d6b40ae24ee509`, qrels train `8f21b5bb07a34bd67c6df1c31435feab44986c8be717854f92291faa67329b1f`, test `ba46b40e07f591409a62c2b6a4e67cb5a0357ef27adb0f89bf8ce68ec723a747` | Benchmark truy xuất tiếng Việt ngoài (61.425 Điều, 3.298 câu hỏi có nhãn mức Điều), chạy trên corpus riêng của nó |
| UIT-ViQuAD 2.0 | `taidng/UIT-ViQuAD2.0` | Không rõ, nhiều khả năng phi thương mại | (xem `data/raw/uit_viquad2`) | Tham khảo cách gán nhãn câu hỏi không có đáp án |
| ExpertQA | `cmalaviya/expertqa` | MIT | — | Tham khảo định nghĩa và cách chấm citation (cùng ALCE) |

Zalo **không phủ** corpus chính: chỉ 27/3.298 cặp nhãn rơi vào các luật trong `selection.json`, còn 413 câu thuộc NĐ 100/2019 (xử phạt
giao thông). Vì vậy bộ câu hỏi cho corpus chính phải tự xây (xem ROADMAP R1).

Lệnh tải các bộ HF: `HF_HUB_DISABLE_XET=1 hf download <repo> --repo-type dataset --local-dir data/raw/<thư mục>`
(tắt Xet vì tải bị ngắt giữa chừng trên mạng hiện tại).

Không dùng: thuvienphapluat.vn, luatvietnam.vn (trang thương mại, điều khoản cấm thu thập); mMARCO (hạn chế thương mại);
dữ liệu BKAI (AGPL).
