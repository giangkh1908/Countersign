import { describe, expect, it } from "vitest";
import { cleanPassage, splitEvidence } from "./passage";

describe("splitEvidence", () => {
  it("quy offset article_text về offset trong đoạn", () => {
    const passage = "Người lao động có quyền đơn phương chấm dứt hợp đồng.";
    const start = 1000;
    const s = splitEvidence(passage, start, start + 4, start + 15);
    expect(s).toEqual({ before: passage.slice(0, 4), hit: passage.slice(4, 15), after: passage.slice(15) });
    expect(s!.before + s!.hit + s!.after).toBe(passage);
  });
  it("đếm theo điểm mã Unicode, không theo đơn vị UTF-16", () => {
    const passage = "a😀b😀c";
    expect(splitEvidence(passage, 0, 2, 3)).toEqual({ before: "a😀", hit: "b", after: "😀c" });
  });
  it("lệch phạm vi hoặc thiếu trường thì không tô", () => {
    expect(splitEvidence("abc", 10, 5, 8)).toBeNull();
    expect(splitEvidence("abc", 0, 1, 99)).toBeNull();
    expect(splitEvidence("abc", 0, 2, 2)).toBeNull();
    expect(splitEvidence("abc", null, 0, 1)).toBeNull();
    expect(splitEvidence("abc", 0, undefined, 1)).toBeNull();
  });
});

describe("cleanPassage", () => {
  it("văn bản thường giữ nguyên", () => {
    expect(cleanPassage("Điều 38. Quyền")).toEqual({ text: "Điều 38. Quyền", altered: false });
  });
  it("bỏ delimiter spotlight", () => {
    const r = cleanPassage("<<BEGIN_UNTRUSTED:abc>> nội dung <<END_UNTRUSTED:abc>>");
    expect(r.text).not.toMatch(/UNTRUSTED/);
    expect(r.altered).toBe(true);
  });
  it("hoàn nguyên datamark thành khoảng trắng", () => {
    const r = cleanPassage("Người^lao^động^có^quyền");
    expect(r.text).toBe("Người lao động có quyền");
    expect(r.altered).toBe(true);
  });
  it("câu có ký tự ^ lẻ nhưng còn khoảng trắng thì không đụng", () => {
    expect(cleanPassage("x ^ y ^ z").altered).toBe(false);
  });
});
