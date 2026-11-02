import { describe, expect, it } from "vitest";
import type { Sentence } from "../../api/types";
import { flagOf, segmentAnswer, splitCites } from "./citedText";

const valid = new Set([1, 2]);

describe("splitCites", () => {
  it("chỉ biến [n] hợp lệ thành nút", () => {
    expect(splitCites("A [1] B [7] C[2].", valid)).toEqual([
      { kind: "text", value: "A " },
      { kind: "cite", n: 1 },
      { kind: "text", value: " B [7] C" },
      { kind: "cite", n: 2 },
      { kind: "text", value: "." },
    ]);
  });
});

describe("segmentAnswer", () => {
  const text = "Câu một [1]. Câu hai 😀 [2].";
  const cps = Array.from(text);
  const s1: Sentence = { id: 0, start: 0, end: cps.indexOf(".") + 1, cites: [1], verdict: "supported" };
  const s2: Sentence = { id: 1, start: s1.end + 1, end: cps.length, cites: [2], verdict: "unsupported" };

  it("cắt theo offset điểm mã và giữ khoảng giữa các câu", () => {
    const segs = segmentAnswer(text, [s1, s2], valid);
    expect(segs.map((s) => s.sentence?.id ?? null)).toEqual([0, null, 1]);
    const joined = segs
      .flatMap((s) => s.parts)
      .map((p) => (p.kind === "text" ? p.value : `[${p.n}]`))
      .join("");
    expect(joined).toBe(text);
  });
  it("offset sai (chồng nhau, vượt biên) thì bỏ hết, không tô lệch", () => {
    expect(segmentAnswer(text, [s2, s1], valid)).toHaveLength(1);
    expect(segmentAnswer(text, [{ ...s1, end: 999 }], valid)).toHaveLength(1);
    expect(segmentAnswer(text, undefined, valid)).toHaveLength(1);
  });
});

describe("flagOf", () => {
  it("chỉ cờ khi kiểm chứng bật và chưa supported", () => {
    expect(flagOf(true, "unverified")).toBe("unverified");
    expect(flagOf(true, "partial")).toBe("partial");
    expect(flagOf(true, "supported")).toBeNull();
    expect(flagOf(true, null)).toBeNull();
    expect(flagOf(false, "unsupported")).toBeNull();
  });
});
