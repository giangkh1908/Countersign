import type { ApiError } from "./errors";

// TODO: AgentEvent đầy đủ theo 07 §3.4.
export type AgentEvent = { event: string; data: unknown };
export type Decision =
  | { type: "edit"; edits: Record<string, string> }
  | { type: "reject"; reason?: string }
  | { type: "refresh" };

// TODO: định nghĩa chi tiết các kiểu dưới đây.
export type CardModel = Record<string, unknown>;
export type ThreadPage = { items: unknown[] };
export type ThreadMessages = { items: unknown[] };
export type RequestCost = Record<string, unknown>;

export interface StreamSink {
  onEvent(e: AgentEvent): void;
  onError(e: ApiError): void;
  onClose(): void;
}

export interface AgentStream {
  run(
    req: { threadId: string | null; text: string; clientMsgId: string },
    sink: StreamSink,
    signal: AbortSignal,
  ): Promise<void>;
  resume(
    req: { threadId: string; interruptId: string; decision: Decision },
    sink: StreamSink,
    signal: AbortSignal,
  ): Promise<void>;
}

export interface ApprovalApi {
  verify(threadId: string, interruptId: string): Promise<CardModel>;
  approve(
    req: { threadId: string; interruptId: string; intentSha256: string },
    sink: StreamSink,
    signal: AbortSignal,
  ): Promise<void>;
}

export interface ThreadApi {
  list(p: { limit: number; before?: string }): Promise<ThreadPage>;
  messages(threadId: string): Promise<ThreadMessages>;
  remove(threadId: string): Promise<void>;
  requestCost(requestId: string): Promise<RequestCost>;
}
