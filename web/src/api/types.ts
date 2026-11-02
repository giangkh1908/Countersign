// Kiểu dùng chung + interface (port) của tầng API. Component chỉ phụ thuộc file này.
import type { z } from "zod";
import type { ApiError } from "./errors";
import type {
  AgentEventSchema,
  AnswerStatusSchema,
  CardSchema,
  CitationSchema,
  CitationsDataSchema,
  InterruptRefSchema,
  MeSchema,
  MessageSchema,
  RequestCostSchema,
  SentenceSchema,
  ThreadMessagesSchema,
  ThreadPageSchema,
  ThreadSummarySchema,
  VerdictSchema,
  VerifyInfoSchema,
} from "./zod";

export type AgentEvent = z.infer<typeof AgentEventSchema>;
export type InterruptRef = z.infer<typeof InterruptRefSchema>;
export type Citation = z.infer<typeof CitationSchema>;
export type Verdict = z.infer<typeof VerdictSchema>;
export type Sentence = z.infer<typeof SentenceSchema>;
export type AnswerStatus = z.infer<typeof AnswerStatusSchema>;
export type VerifyInfo = z.infer<typeof VerifyInfoSchema>;
export type CitationsData = z.infer<typeof CitationsDataSchema>;
export type Me = z.infer<typeof MeSchema>;
/** Phản hồi thô của POST /api/intents/verify; display_fields phân loại ở features/approval/cardModel. */
export type CardModel = z.infer<typeof CardSchema>;
export type ThreadSummary = z.infer<typeof ThreadSummarySchema>;
export type ThreadPage = z.infer<typeof ThreadPageSchema>;
export type ChatMessage = z.infer<typeof MessageSchema>;
export type ThreadMessages = z.infer<typeof ThreadMessagesSchema>;
export type RequestCost = z.infer<typeof RequestCostSchema>;

export type Decision =
  | { type: "edit"; edits: Record<string, string> }
  | { type: "reject"; reason?: string }
  | { type: "refresh" };

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
  /** 410 intent_expired / 422 intent_unrenderable|intent_mismatch -> ném ApiError. */
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

export interface AuthApi {
  me(): Promise<Me>;
  /** POST /auth/logout -> URL cần chuyển tới (đăng xuất phía IdP). */
  logout(): Promise<{ redirectUrl: string }>;
}

export interface Api {
  agent: AgentStream;
  approvals: ApprovalApi;
  threads: ThreadApi;
  auth: AuthApi;
}
