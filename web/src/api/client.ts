// src/api/client.ts — nơi DUY NHẤT được dùng fetch / SSE (leak-grep contracts §9.1.8).
import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { ZodType } from "zod";
import { ApiError, parseErrorBody } from "./errors";

export interface RequestOptions<T> {
  method?: string;
  body?: unknown;
  schema: ZodType<T>;
  signal?: AbortSignal;
}

export interface SseHandlers<E> {
  onEvent: (e: E) => void;
  onError: (e: ApiError) => void;
  onClose: () => void;
}

export type SseOptions<E> = { body: unknown; schema: ZodType<E>; signal: AbortSignal } & SseHandlers<E>;

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function csrfCookieName(): string {
  return location.protocol === "https:" ? "__Host-csrf" : "csrf";
}

export function readCsrf(): string {
  const prefix = csrfCookieName() + "=";
  const hit = document.cookie.split("; ").find((c) => c.startsWith(prefix));
  return hit ? decodeURIComponent(hit.slice(prefix.length)) : "";
}

let navigate: (url: string) => void = (url) => location.assign(url);
/** Chỉ dùng trong test: thay hành vi chuyển trang. */
export function setNavigator(fn: (url: string) => void): void {
  navigate = fn;
}

function toLogin(): never {
  const back = encodeURIComponent(location.pathname + location.search);
  navigate(`/auth/login?return_to=${back}`);
  throw new ApiError(401, "session_expired", "", false);
}

export async function request<T>(path: string, o: RequestOptions<T>): Promise<T> {
  const method = o.method ?? "GET";
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    signal: o.signal,
    headers: {
      Accept: "application/json",
      ...(o.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(MUTATING.has(method) ? { "X-CSRF-Token": readCsrf() } : {}),
    },
    body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
  });
  if (!res.ok) {
    const err = await parseErrorBody(res);
    if (res.status === 401 && err.code === "session_expired") toLogin();
    throw err;
  }
  if (res.status === 204) return o.schema.parse(undefined);
  const parsed = o.schema.safeParse(await res.json());
  if (!parsed.success) throw new ApiError(502, "bad_response", "", false);
  return parsed.data;
}

class FatalSse extends Error {}

export async function sse<E>(path: string, o: SseOptions<E>): Promise<void> {
  let failure: ApiError | null = null;
  try {
    await fetchEventSource(path, {
      method: "POST",
      credentials: "same-origin",
      signal: o.signal,
      openWhenHidden: true,
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "X-CSRF-Token": readCsrf(),
      },
      body: JSON.stringify(o.body),
      async onopen(res) {
        if (res.ok && res.headers.get("content-type")?.startsWith("text/event-stream")) return;
        const err = res.ok ? new ApiError(502, "bad_response", "", false) : await parseErrorBody(res);
        if (res.status === 401 && err.code === "session_expired") {
          try {
            toLogin();
          } catch {
            /* trang sắp chuyển hướng */
          }
        }
        failure = err;
        throw new FatalSse();
      },
      onmessage(m) {
        if (!m.event) return; // comment/keepalive
        let data: unknown;
        try {
          data = JSON.parse(m.data);
        } catch {
          failure = new ApiError(502, "bad_event", "", false);
          throw new FatalSse();
        }
        const parsed = o.schema.safeParse({ event: m.event, data });
        if (parsed.success) o.onEvent(parsed.data);
        else {
          failure = new ApiError(502, "bad_event", "", false);
          throw new FatalSse();
        }
      },
      onerror(e) {
        throw e; // KHÔNG tự thử lại: POST không idempotent
      },
      onclose() {
        o.onClose();
      },
    });
  } catch (e) {
    if (o.signal.aborted) return;
    o.onError(failure ?? (e instanceof ApiError ? e : new ApiError(0, "network", "", true)));
  }
}
