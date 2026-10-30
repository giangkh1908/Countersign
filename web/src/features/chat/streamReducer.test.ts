import { describe, expect, it } from "vitest";
import { initialStream, streamReducer } from "./streamReducer";

describe("streamReducer", () => {
  it("token rồi done", () => {
    let s = streamReducer(initialStream, { event: "start", text: "hi", threadId: null });
    s = streamReducer(s, { event: "token", data: { text: "A" } });
    s = streamReducer(s, { event: "token", data: { text: "B" } });
    s = streamReducer(s, { event: "done", data: { status: "completed" } });
    expect(s.text).toBe("AB");
    expect(s.phase).toBe("done");
  });
  it("interrupt + done interrupted -> awaiting_approval", () => {
    let s = streamReducer(initialStream, { event: "start", text: "x", threadId: "t" });
    s = streamReducer(s, {
      event: "interrupt",
      data: { interrupt_id: "i", intent_id: "n", op: "close_ticket", expires_at: "2099-01-01T00:00:00Z" },
    });
    s = streamReducer(s, { event: "done", data: { status: "interrupted" } });
    expect(s.phase).toBe("awaiting_approval");
    expect(streamReducer(s, { event: "settle" }).interrupt?.interrupt_id).toBe("i");
  });
  it("closed khi đang stream -> lỗi stream_closed", () => {
    const s = streamReducer({ ...initialStream, phase: "streaming" }, { event: "closed" });
    expect(s.error?.code).toBe("stream_closed");
  });
});
