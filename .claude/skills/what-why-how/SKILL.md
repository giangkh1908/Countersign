---
name: what-why-how
description: Dùng mỗi khi xử lý một vấn đề — sửa lỗi, thêm/đổi tính năng, cấu hình, quyết định kiến trúc, trả lời câu hỏi "có làm được X không", review kết quả worker. Bắt buộc trả lời đủ 3 câu What / Why / How trước khi hành động và trong báo cáo cuối.
---

# What / Why / How

Mọi vấn đề phải trả lời được đủ 3 câu. Thiếu câu nào thì chưa được hành động, chưa được báo xong.

## Ba câu hỏi

**What: vấn đề hoặc thay đổi là gì?**
- Mô tả cụ thể: hiện trạng → mong muốn, phạm vi (gói, file, service nào).
- Có bằng chứng: `file:dòng`, log, output lệnh, kết quả test. Không mô tả theo trí nhớ.

**Why: tại sao?**
- Lỗi: nguyên nhân gốc đã kiểm chứng, không phải triệu chứng.
- Thay đổi/quyết định: lý do chọn, ràng buộc liên quan (Ports & Adapters §9, ADR, CLAUDE.md), phương án bị loại và vì sao.
- Chưa chắc thì ghi rõ "chưa kiểm chứng", rồi điều tra tiếp hoặc hỏi user. Không đoán rồi làm.

**How: làm thế nào?**
- Các bước cụ thể, file sẽ đổi, ai làm (tự làm / `worker` / `reader`).
- Cách kiểm chứng: lệnh test, tiêu chí xong.
- Cách rollback (branch, backup) nếu thay đổi trạng thái.

## Khi nào áp dụng

1. **Trước khi làm:** nêu What/Why/How ngắn gọn rồi mới hành động hoặc giao việc.
2. **Khi giao worker/reader:** prompt phải có đủ What (mục tiêu), Why (bối cảnh, ràng buộc), How (bước, tiêu chí xong); yêu cầu báo cáo theo cùng 3 mục.
3. **Khi báo cáo cho user:** kết thúc bằng 3 mục; How ghi những gì đã làm thật, kèm kết quả kiểm chứng.

## Định dạng

```
**What:** <1–3 dòng>
**Why:** <1–3 dòng>
**How:** <các bước / đã làm + kết quả kiểm chứng>
```

Ngắn gọn, tiếng Việt. Việc nhỏ thì mỗi mục một dòng là đủ, nhưng không bỏ mục nào.
