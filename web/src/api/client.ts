// src/api/client.ts — nơi DUY NHẤT được dùng fetch / SSE (leak-grep contracts §9.1.8).
import type { ZodType } from "zod";
import type { ApiError } from "./errors";

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

// TODO: fetch same-origin + CSRF (X-CSRF-Token) + xử lý 401 -> /auth/login + zod parse (07 §3.3).
export function request<T>(path: string, o: RequestOptions<T>): Promise<T> {
  void path;
  void o;
  return Promise.reject(new Error("request(): chưa cài đặt"));
}

// TODO: fetchEventSource qua POST, không tự thử lại, zod parse từng event (07 §3.3).
export function sse<E>(path: string, o: SseOptions<E>): Promise<void> {
  void path;
  void o;
  return Promise.reject(new Error("sse(): chưa cài đặt"));
}
