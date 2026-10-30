import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { server } from "../test/msw/server";
import { sseResponse } from "../test/msw/handlers";
import { request, setNavigator, sse } from "./client";
import { ApiError } from "./errors";
import { AgentEventSchema } from "./zod";

const Schema = z.object({ ok: z.boolean() });

describe("request()", () => {
  it("gửi X-CSRF-Token từ cookie cho POST, không gửi cho GET", async () => {
    document.cookie = "csrf=tok123";
    const seen: (string | null)[] = [];
    server.use(
      http.post("/api/x", ({ request: r }) => {
        seen.push(r.headers.get("x-csrf-token"));
        return HttpResponse.json({ ok: true });
      }),
      http.get("/api/x", ({ request: r }) => {
        seen.push(r.headers.get("x-csrf-token"));
        return HttpResponse.json({ ok: true });
      }),
    );
    await request("/api/x", { method: "POST", body: { a: 1 }, schema: Schema });
    await request("/api/x", { schema: Schema });
    expect(seen).toEqual(["tok123", null]);
  });

  it("session_expired -> chuyển về /auth/login", async () => {
    const nav = vi.fn();
    setNavigator(nav);
    server.use(
      http.get("/api/me", () =>
        HttpResponse.json(
          { error: { code: "session_expired", message: "x", retryable: false, request_id: "r" } },
          { status: 401 },
        ),
      ),
    );
    await expect(request("/api/me", { schema: Schema })).rejects.toBeInstanceOf(ApiError);
    expect(nav).toHaveBeenCalledWith(expect.stringMatching(/^\/auth\/login\?return_to=/));
  });

  it("lỗi JSON khác được ném với code/retryable", async () => {
    server.use(
      http.get("/api/y", () =>
        HttpResponse.json({ error: { code: "rate_limited", message: "m", retryable: true } }, { status: 429 }),
      ),
    );
    await expect(request("/api/y", { schema: Schema })).rejects.toMatchObject({
      status: 429,
      code: "rate_limited",
      retryable: true,
    });
  });

  it("zod từ chối response sai", async () => {
    server.use(http.get("/api/z", () => HttpResponse.json({ ok: "no" })));
    await expect(request("/api/z", { schema: Schema })).rejects.toMatchObject({ code: "bad_response" });
  });
});

function opts(over: Partial<Parameters<typeof sse<z.infer<typeof AgentEventSchema>>>[1]> = {}) {
  return {
    body: {},
    schema: AgentEventSchema,
    signal: new AbortController().signal,
    onEvent: () => {},
    onError: () => {},
    onClose: () => {},
    ...over,
  };
}

describe("sse()", () => {
  it("parse event, bỏ qua keepalive, rồi onClose", async () => {
    server.use(
      http.post("/api/chat", () =>
        sseResponse([
          { event: "token", data: { text: "Xin " } },
          { event: "token", data: { text: "chào" } },
          { event: "done", data: { status: "completed", message_id: "m1" } },
        ]),
      ),
    );
    const events: string[] = [];
    const onClose = vi.fn();
    const onError = vi.fn();
    await sse("/api/chat", opts({ onEvent: (e) => events.push(e.event), onClose, onError }));
    expect(events).toEqual(["token", "token", "done"]);
    expect(onClose).toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("event lạ -> onError bad_event", async () => {
    server.use(http.post("/api/chat", () => sseResponse([{ event: "weird", data: {} }])));
    const onError = vi.fn();
    await sse("/api/chat", opts({ onError }));
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: "bad_event" }));
  });

  it("lỗi JSON trước luồng -> onError với code của BFF", async () => {
    server.use(
      http.post("/api/chat", () =>
        HttpResponse.json({ error: { code: "forbidden", message: "", retryable: false } }, { status: 403 }),
      ),
    );
    const onError = vi.fn();
    await sse("/api/chat", opts({ onError }));
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: "forbidden", status: 403 }));
  });
});
