// Làm sạch và cắt đoạn nguồn để hiển thị. Nội dung tài liệu là dữ liệu không tin cậy.

// Dấu spotlight dành cho mô hình (docs-mcp/services/spotlight.py). `text` của server lẽ ra là bản thô,
// nhưng UI vẫn phòng thủ: người đọc không bao giờ thấy delimiter hay datamark.
const FAKE_DELIM = /<<\s*(?:BEGIN|END)_UNTRUSTED[^>]*>>/gi;
const DATAMARKS = ["^", "~", "¦", "‡", "¤", "¬"];

export interface CleanedPassage {
  text: string;
  /** Đã bỏ delimiter/datamark: offset từ server không còn khớp, không được tô. */
  altered: boolean;
}

export function cleanPassage(raw: string): CleanedPassage {
  let text = raw.replace(FAKE_DELIM, "");
  let altered = text !== raw;
  // Datamark thay mọi khoảng trắng bằng đúng một ký hiệu: văn bản không còn khoảng trắng mà có ký hiệu lặp.
  if (!/\s/u.test(text.trim())) {
    for (const mark of DATAMARKS) {
      if (text.split(mark).length - 1 >= 2) {
        text = text.split(mark).join(" ");
        altered = true;
        break;
      }
    }
  }
  return { text, altered };
}

export interface EvidenceSplit {
  before: string;
  hit: string;
  after: string;
}

/**
 * Tách đoạn thành trước / câu được trích / sau. `evidenceStart/End` và `charStart` cùng hệ toạ độ
 * (article_text, điểm mã Unicode); trả null khi thiếu hoặc lệch phạm vi (không tô sai chỗ).
 */
export function splitEvidence(
  passage: string,
  charStart: number | null | undefined,
  evidenceStart: number | null | undefined,
  evidenceEnd: number | null | undefined,
): EvidenceSplit | null {
  if (charStart == null || evidenceStart == null || evidenceEnd == null) return null;
  const cps = Array.from(passage);
  const from = evidenceStart - charStart;
  const to = evidenceEnd - charStart;
  if (from < 0 || to <= from || to > cps.length) return null;
  return {
    before: cps.slice(0, from).join(""),
    hit: cps.slice(from, to).join(""),
    after: cps.slice(to).join(""),
  };
}
