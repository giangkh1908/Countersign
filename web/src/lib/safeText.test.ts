import { describe, expect, it } from "vitest";
import { inspectText, safeText } from "./safeText";

describe("safeText", () => {
  it("escape bidi override", () => {
    expect(safeText("a‮b")).toBe("a⟦U+202E⟧b");
    expect(inspectText("a‮b").blocked).toBe(true);
  });
  it("điều khiển bị chặn, xuống dòng chỉ cho longtext", () => {
    expect(inspectText("a\nb").blocked).toBe(true);
    expect(inspectText("a\nb", true).blocked).toBe(false);
    expect(inspectText("a\u0007b", true).blocked).toBe(true);
  });
  it("zero-width: cảnh báo nhưng không chặn", () => {
    expect(inspectText("a​b")).toEqual({ blocked: false, hidden: true });
    expect(safeText("a​b")).toBe("a⟦U+200B⟧b");
  });
});
