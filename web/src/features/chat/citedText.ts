// Thuần túy: chia câu trả lời thành đoạn theo `sentences[]` và tách mã [n]. Test được không cần React.
import type { Sentence, Verdict } from "../../api/types";

export type Part = { kind: "text"; value: string } | { kind: "cite"; n: number };

export interface Segment {
  /** null = đoạn nằm giữa các câu (xuống dòng, đầu mục...). */
  sentence: Sentence | null;
  parts: Part[];
}

const CITE = /\[(\d{1,3})\]/g;

/** Tách [n]; chỉ mã n có trong `valid` mới thành nút, mã khác giữ nguyên là chữ. */
export function splitCites(text: string, valid: ReadonlySet<number>): Part[] {
  const out: Part[] = [];
  let last = 0;
  for (const m of text.matchAll(CITE)) {
    const n = Number(m[1]);
    if (!valid.has(n)) continue;
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", value: text.slice(last, at) });
    out.push({ kind: "cite", n });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
  return out;
}

/** Danh sách câu hợp lệ: trong phạm vi, tăng dần, không chồng nhau; sai thì bỏ cả danh sách (không tô lệch). */
function usable(sentences: Sentence[] | undefined, length: number): Sentence[] {
  if (!sentences || sentences.length === 0) return [];
  let prev = 0;
  for (const s of sentences) {
    if (s.end <= s.start || s.start < prev || s.end > length) return [];
    prev = s.end;
  }
  return sentences;
}

export function segmentAnswer(text: string, sentences: Sentence[] | undefined, valid: ReadonlySet<number>): Segment[] {
  const cps = Array.from(text);
  const list = usable(sentences, cps.length);
  if (list.length === 0) return [{ sentence: null, parts: splitCites(text, valid) }];
  const segs: Segment[] = [];
  let pos = 0;
  const gap = (to: number) => {
    if (to > pos) segs.push({ sentence: null, parts: splitCites(cps.slice(pos, to).join(""), valid) });
  };
  for (const s of list) {
    gap(s.start);
    segs.push({ sentence: s, parts: splitCites(cps.slice(s.start, s.end).join(""), valid) });
    pos = s.end;
  }
  gap(cps.length);
  return segs;
}

/** Cờ cảnh báo chỉ hiện khi kiểm chứng bật và câu là khẳng định chưa được `supported`. */
export function flagOf(verifyEnabled: boolean, verdict: Verdict | null | undefined): Exclude<Verdict, "supported"> | null {
  if (!verifyEnabled || !verdict || verdict === "supported") return null;
  return verdict;
}
